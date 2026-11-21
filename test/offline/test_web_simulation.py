"""FR-TRD-001..006, INV-TRD-001..003; ADR-001-simulated-trading-system.md.

Exercise actual core safety, portfolio, approval and persistence using temp data.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from test.offline.web_fixture_app import SECRET, build_fixture_tree, make_run_client

pytestmark = pytest.mark.unit
NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self):
        self.value = NOW

    def now(self):
        return self.value

    def is_simulated(self):
        return False

    def simulation_date(self):
        return None


@pytest.fixture()
def sim(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree)
    service = client.app.state.simulation
    service.clock = FixedClock()
    yield tree, client, service
    service.close()


def initialize(client, cash="10000.00"):
    result = client.post(
        "/api/simulation/account", json={"initial_cash": cash, "confirm": "INITIALIZE"}
    )
    assert result.status_code == 200, result.text
    return result.json()


def decision_body(client, state=None, **overrides):
    state = state or client.get("/api/simulation").json()
    report = next(
        item
        for item in client.get("/api/simulation/reports").json()["items"]
        if item["ticker"] == "NVDA"
    )
    return {
        "client_request_id": uuid.uuid4().hex,
        "artifact_id": report["artifact_id"],
        "quote_price": "100.00",
        "quote_as_of": NOW.isoformat(),
        "expected_version": state["snapshot"]["version"],
        "expected_account_id": state["account_id"],
        **overrides,
    }


def approval_body(state, approved=True, **overrides):
    return {
        "approved": approved,
        "approver": "Local reviewer",
        "reason": "Reviewed simulated position size.",
        "expected_version": state["snapshot"]["version"],
        "expected_account_id": state["account_id"],
        **overrides,
    }


def wait_job(client, job_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/simulation/jobs/{job_id}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in {"starting", "running"}:
            return value
        time.sleep(0.01)
    pytest.fail("Offline simulation did not finish")


def scenario_body(**overrides):
    return {
        "source": "scenario",
        "symbol": "NVDA",
        "start": "2026-11-02",
        "end": "2026-11-03",
        "initial_cash": "10000.00",
        "rows": [
            {"date": "2026-11-02", "action": "BUY", "price": "100"},
            {"date": "2026-11-03", "action": "SELL", "price": "105"},
        ],
        **overrides,
    }


def test_empty_account_and_verified_audit_are_not_fabricated(sim):
    _, client, _ = sim
    state = client.get("/api/simulation").json()
    assert state["initialized"] is False and state["snapshot"] is None
    assert client.get("/api/simulation/audit").json()["verified"] is None
    assert client.get("/api/simulation/reports").json()["items"]


def test_real_pipeline_fill_decimal_snapshot_idempotency_and_restart(sim):
    tree, client, service = sim
    state = initialize(client)
    body = decision_body(client, state)
    response = client.post("/api/simulation/decisions", json=body)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["evaluation"]["status"] == "APPROVED"
    assert result["execution"]["order"]["quantity"] == "5.000000"
    assert result["execution"]["order"]["fee"] == "0.25"
    assert client.post("/api/simulation/decisions", json=body).json() == response.json()
    assert service.runtime.engine.execution_count == 1
    snapshot = client.get("/api/simulation").json()["snapshot"]
    assert snapshot["cash"] == "9499.75" and snapshot["total_equity"] == "9999.75"
    assert snapshot["positions"][0]["quantity"] == "5.000000"
    assert (
        client.post("/api/simulation/decisions", json={**body, "quote_price": "101"}).status_code
        == 409
    )
    service.close()
    restarted = make_run_client(tree)
    restarted.app.state.simulation.clock = FixedClock()
    try:
        restored = restarted.get("/api/simulation").json()
        assert restored["snapshot"] == snapshot
        assert restored["account_id"] == state["account_id"]
        assert restarted.post("/api/simulation/decisions", json=body).json() == response.json()
        audit = restarted.get(
            "/api/simulation/audit", params={"event_type": "ORDER_EXECUTED"}
        ).json()
        assert audit["verified"] and audit["total"] == 1
        assert SECRET not in json.dumps(restored)
        assert str(tree.root) not in json.dumps(audit)
    finally:
        restarted.app.state.simulation.close()


@pytest.mark.parametrize("approved", [True, False])
def test_pending_requires_issued_human_approval_and_cannot_execute_twice(sim, approved):
    _, client, service = sim
    state = initialize(client, "100000.00")
    response = client.post("/api/simulation/decisions", json=decision_body(client, state))
    assert response.status_code == 200, response.text
    assert response.json()["result"]["evaluation"]["status"] == "PENDING_APPROVAL"
    pending = client.get("/api/simulation").json()["pending"][0]
    assert service.runtime.engine.execution_count == 0
    path = f"/api/simulation/approvals/{pending['request_id']}"
    body = approval_body(state, approved)
    result = client.post(path, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["evaluation"]["status"] == (
        "APPROVED" if approved else "REJECTED"
    )
    assert service.runtime.engine.execution_count == int(approved)
    assert client.post(path, json=body).status_code == 409
    assert client.post("/api/simulation/approvals/forged", json=body).status_code == 409
    assert not client.get("/api/simulation").json()["pending"]


@pytest.mark.parametrize("case", ["expired", "stale_quote", "stale", "reset"])
def test_approval_invalidated_by_expiry_quote_version_or_account_epoch(sim, case):
    _, client, service = sim
    state = initialize(client, "100000.00")
    client.post("/api/simulation/decisions", json=decision_body(client, state))
    pending = client.get("/api/simulation").json()["pending"][0]
    if case == "expired":
        service.clock.value += timedelta(seconds=901)
    elif case == "stale_quote":
        service.clock.value += timedelta(seconds=301)
    elif case == "stale":
        service.runtime.portfolio.mark({"NVDA": Decimal("101")})
    else:
        reset = client.post(
            "/api/simulation/account",
            json={
                "initial_cash": "100000.00",
                "confirm": "RESET",
                "expected_version": state["snapshot"]["version"],
                "expected_account_id": state["account_id"],
            },
        )
        assert reset.status_code == 200
        assert reset.json()["account_id"] != state["account_id"]
    result = client.post(
        f"/api/simulation/approvals/{pending['request_id']}", json=approval_body(state)
    )
    assert result.status_code in {409, 422}
    assert service.runtime.engine.execution_count == 0


def test_restart_does_not_restore_pending_approval_authority(sim):
    tree, client, service = sim
    state = initialize(client, "100000.00")
    client.post("/api/simulation/decisions", json=decision_body(client, state))
    pending = client.get("/api/simulation").json()["pending"][0]
    service.close()
    restarted = make_run_client(tree)
    restarted.app.state.simulation.clock = FixedClock()
    try:
        restored = restarted.get("/api/simulation").json()
        assert not restored["pending"]
        assert (
            restarted.post(
                f"/api/simulation/approvals/{pending['request_id']}", json=approval_body(state)
            ).status_code
            == 409
        )
    finally:
        restarted.app.state.simulation.close()


def test_reset_preserves_audit_and_rejects_old_account_epoch(sim):
    _, client, _ = sim
    state = initialize(client)
    old = decision_body(client, state)
    client.post("/api/simulation/decisions", json=old)
    state = client.get("/api/simulation").json()
    response = client.post(
        "/api/simulation/account",
        json={
            "initial_cash": "2000",
            "confirm": "RESET",
            "expected_version": state["snapshot"]["version"],
            "expected_account_id": state["account_id"],
        },
    )
    assert response.status_code == 200, response.text
    reset = response.json()
    assert reset["snapshot"]["cash"] == "2000.00" and not reset["snapshot"]["positions"]
    old["client_request_id"] = uuid.uuid4().hex
    assert client.post("/api/simulation/decisions", json=old).status_code == 409
    events = client.get("/api/simulation/audit").json()["items"]
    assert {"STATE_RESET", "ORDER_EXECUTED"} <= {event["event_type"] for event in events}


@pytest.mark.parametrize("rating,action", [("Hold", "HOLD"), ("unrecognized", "REVIEW")])
def test_no_action_ratings_never_create_fills(sim, rating, action):
    tree, client, service = sim
    (tree.run_dir / "reports" / "final_trade_decision.md").write_text(f"**Rating**: {rating}")
    state = initialize(client)
    result = client.post("/api/simulation/decisions", json=decision_body(client, state))
    assert result.status_code == 200, result.text
    assert result.json()["result"]["evaluation"]["status"] == "NO_ACTION"
    assert result.json()["result"]["decision"]["action"] == action
    assert service.runtime.engine.execution_count == 0


@pytest.mark.parametrize("value", [100, 100.5, True, "NaN", "Infinity", "-1", "../secret"])
def test_invalid_decimal_requests_never_initialize_an_account(sim, value):
    _, client, service = sim
    assert (
        client.post(
            "/api/simulation/account", json={"initial_cash": value, "confirm": "INITIALIZE"}
        ).status_code
        == 422
    )
    assert service.runtime is None


@pytest.mark.parametrize(
    "patch",
    [
        {"quote_price": "0"},
        {"quote_as_of": (NOW + timedelta(seconds=10)).isoformat()},
        {"quote_as_of": (NOW - timedelta(seconds=301)).isoformat()},
    ],
)
def test_core_hard_quote_rules_reject_without_fill(sim, patch):
    _, client, service = sim
    state = initialize(client)
    result = client.post("/api/simulation/decisions", json=decision_body(client, state, **patch))
    assert result.status_code == 200, result.text
    assert result.json()["result"]["evaluation"]["status"] == "REJECTED"
    assert service.runtime.engine.execution_count == 0


def test_no_execution_or_arbitrary_config_input_and_csrf_are_allowed(sim):
    _, client, _ = sim
    assert (
        client.post(
            "/api/simulation/account", json={"initial_cash": "10000", "confirm": "RESET"}
        ).status_code
        == 409
    )
    state = initialize(client)
    body = decision_body(client, state)
    for key, value in [
        ("quantity", "100000"),
        ("status", "APPROVED"),
        ("config", {}),
        ("state_path", "/private/secret"),
    ]:
        assert (
            client.post("/api/simulation/decisions", json={**body, key: value}).status_code == 422
        )
    result = client.post(
        "/api/simulation/decisions", json=body, headers={"X-CSRF-Token": "invalid"}
    )
    assert result.status_code == 403
    assert "/api/simulation/jobs/{job_id}/cancel" not in client.get("/openapi.json").json()["paths"]
    assert client.post("/api/simulation/jobs/unknown/cancel", json={}).status_code in {404, 405}


@pytest.mark.parametrize("target", ["audit", "state"])
def test_tampered_storage_fails_closed_without_silent_reset(sim, target):
    _, client, service = sim
    state = initialize(client)
    body = decision_body(client, state)
    location = service.path("account", "audit.jsonl" if target == "audit" else "state.json")
    location.write_text("tampered state")
    response = client.post("/api/simulation/decisions", json=body)
    assert response.status_code == 409, response.text
    assert location.read_text() == "tampered state"
    assert service.runtime.engine.execution_count == 0


def test_failed_fill_persistence_blocks_mutation_but_retains_audit(sim, monkeypatch):
    _, client, service = sim
    state = initialize(client)
    monkeypatch.setattr(
        service.runtime.store,
        "save",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private server path")),
    )
    result = client.post("/api/simulation/decisions", json=decision_body(client, state))
    assert result.status_code == 409
    assert "private server path" not in result.text
    assert service.poisoned
    assert client.get("/api/simulation").status_code == 409
    assert client.get("/api/simulation/audit").json()["verified"] is True


def test_workspace_owner_and_single_active_slot_are_enforced(sim):
    tree, client, service = sim
    initialize(client)
    other = make_run_client(tree)
    try:
        assert other.get("/api/simulation").status_code == 409
    finally:
        other.app.state.simulation.close()
    coordinator = client.app.state.coordinator
    with coordinator.external_run("sim_busy", {"status": "running"}):
        assert (
            client.post(
                "/api/simulation/account", json={"initial_cash": "1", "confirm": "INITIALIZE"}
            ).status_code
            == 409
        )
        assert client.post("/api/simulation/jobs", json=scenario_body()).status_code == 409
        assert client.get("/api/runs/active").json()["kind"] == "simulation"
    assert coordinator.active_snapshot() is None


def test_fixed_storage_namespace_rejects_symlink_escape(tmp_path):
    tree = build_fixture_tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tree.results_dir / "simulated_trading").symlink_to(outside, target_is_directory=True)
    client = make_run_client(tree)
    assert client.get("/api/simulation").status_code == 409
    assert not list(outside.iterdir())


def test_walk_forward_core_scenario_resume_account_isolation_and_audit(sim):
    tree, client, _ = sim
    account = initialize(client)["snapshot"]
    started = client.post("/api/simulation/jobs", json=scenario_body())
    assert started.status_code == 202, started.text
    result = wait_job(client, started.json()["run_id"])
    assert result["status"] == "completed", result
    assert result["summary"]["executions"] == 2
    assert result["cursor"]["last_completed_date"] == "2026-11-03"
    assert client.get("/api/simulation").json()["snapshot"] == account
    audit = client.get(
        "/api/simulation/audit", params={"run_id": result["run_id"], "event_type": "ORDER_EXECUTED"}
    ).json()
    assert audit["verified"] and audit["total"] == 2
    resume = client.post("/api/simulation/jobs", json=scenario_body(resume_id=result["run_id"]))
    assert resume.status_code == 202
    repeated = wait_job(client, result["run_id"])
    assert repeated["snapshot"] == result["snapshot"]
    assert repeated["summary"]["executions"] == 0
    assert (
        client.post(
            "/api/simulation/jobs",
            json=scenario_body(resume_id=result["run_id"], initial_cash="9999"),
        ).status_code
        == 409
    )
    assert str(tree.root) not in json.dumps(result)


def test_walk_forward_pending_orders_are_not_automatically_approved(sim):
    _, client, _ = sim
    body = scenario_body(initial_cash="100000.00")
    for row in body["rows"]:
        row["action"] = "BUY"
    started = client.post("/api/simulation/jobs", json=body)
    result = wait_job(client, started.json()["run_id"])
    assert result["status"] == "completed"
    assert result["summary"]["pending_approvals"] == 2
    assert result["summary"]["executions"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "../../secret"},
        {"end": "2026-11-01"},
        {"rows": []},
        {"rows": [{"date": "2026-11-01", "action": "BUY", "price": "100"}]},
        {"source": "research"},
        {"initial_cash": 10000},
    ],
)
def test_invalid_simulation_job_never_starts(sim, changes):
    _, client, service = sim
    result = client.post("/api/simulation/jobs", json=scenario_body(**changes))
    assert result.status_code in {409, 422}
    assert not service.jobs.running


def test_research_provider_uses_core_adapter_and_isolated_portfolio_context(sim, monkeypatch):
    import pandas as pd

    _, client, _ = sim
    books = []

    class Graph:
        def __init__(self, **kwargs):
            assert "research_memory.md" in kwargs["config"]["memory_log_path"]

        def propagate(self, symbol, day, *, asset_type, portfolio):
            books.append(portfolio)
            return {"final_trade_decision": "**Rating**: Buy", "trade_date": day}, "Buy"

    monkeypatch.setattr("tradingagents_web.runtime.simulation_jobs.WebAnalysisGraph", Graph)
    monkeypatch.setattr(
        "tradingagents.dataflows.stockstats_utils.load_ohlcv",
        lambda symbol, day, **kwargs: pd.DataFrame({"Date": [day], "Close": [100.0]}),
    )
    started = client.post("/api/simulation/jobs", json=scenario_body(source="research", rows=[]))
    result = wait_job(client, started.json()["run_id"])
    assert result["status"] == "completed", result
    assert len(books) == 2
    assert books[0].positions == () or len(books[0].positions) == 0
    assert len(books[1].positions) == 1
    assert result["summary"]["executions"] == 2
