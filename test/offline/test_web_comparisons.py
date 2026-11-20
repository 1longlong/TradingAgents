"""NFR-CMP-001/002/003, ADR-002, INV-9, INV-WEB-001/014: pure server replay."""

from __future__ import annotations

import pytest

from test.offline.web_fixture_app import build_fixture_tree, make_run_client

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "case_id,rounds,reason,early",
    [
        ("D", (3, 1), "no_new_evidence", True),
        ("E", (3, 3), "max_rounds_reached", False),
        ("F", (3, 1), "budget_exhausted", True),
        ("G", (2, 2), "input_exhausted", False),
    ],
)
def test_scripted_replay_preserves_core_outcomes_and_pending_rubric(
    tmp_path, case_id, rounds, reason, early
):
    tree = build_fixture_tree(tmp_path)
    client = make_run_client(tree)
    before = sorted(
        (str(path.relative_to(tree.root)), path.stat().st_size)
        for path in tree.root.rglob("*")
        if path.is_file()
    )
    result = client.get(f"/api/comparisons/{case_id}")
    assert result.status_code == 200
    data = result.json()
    assert data["scope"] == "scripted_offline"
    assert (data["fixed"]["debate_rounds"], data["dynamic"]["debate_rounds"]) == rounds
    assert data["dynamic"]["stop_reason"] == reason
    assert data["dynamic"]["early_stopped"] is early
    assert data["fixed"]["identity"] == data["dynamic"]["identity"]
    assert data["dynamic"]["traceability_status"] == "pending"
    assert data["dynamic"]["traceability_scores"] == []
    assert data["dynamic"]["estimated"] is True
    download = client.get(f"/api/comparisons/{case_id}/download")
    assert download.status_code == 200 and download.json() == data
    assert "attachment" in download.headers["content-disposition"]
    assert client.get(f"/api/comparisons/{case_id}").json() == data
    after = sorted(
        (str(path.relative_to(tree.root)), path.stat().st_size)
        for path in tree.root.rglob("*")
        if path.is_file()
    )
    assert before == after
    assert client.get("/api/runs/active").json() == {"run_id": None}


def test_catalog_keeps_regression_separate_and_mismatches_have_no_report(tmp_path):
    client = make_run_client(build_fixture_tree(tmp_path))
    catalog = client.get("/api/comparisons").json()
    assert catalog["representative_cases"] == 3 and catalog["regression_cases"] == 1
    assert [item["case_id"] for item in catalog["cases"]] == ["D", "E", "F", "G"]
    assert catalog["cases"][-1]["role"] == "regression"
    assert len(catalog["rubric_dimensions"]) == 4
    for suffix in ("", "/download"):
        result = client.get(f"/api/comparisons/D{suffix}?dynamic_case_id=E")
        assert result.status_code == 422
        assert result.json()["error"]["fields"]["reason"] == "identity_mismatch"
        assert "report" not in result.json()
        assert "Content-Disposition" not in result.headers
    assert client.get("/api/comparisons/unknown").status_code == 404
    assert client.get("/api/comparisons/D?dynamic_case_id=unknown").status_code == 404


def test_comparison_response_limits_are_effective(tmp_path):
    client = make_run_client(build_fixture_tree(tmp_path), max_report_bytes=100)
    for path in ("/api/comparisons", "/api/comparisons/D", "/api/comparisons/D/download"):
        assert client.get(path).status_code == 413
