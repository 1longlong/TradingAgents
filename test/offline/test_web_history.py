"""Read-only WebUI history and report contracts.

Covers REQ-WEB-010 and the history read path of ADR-005. The tests deliberately
fail as ``EXPECTED-UNIMPLEMENTED`` until ``tradingagents_web`` exists; they must
not be weakened into skips.
"""

from __future__ import annotations

import json
import re
import zipfile
from io import BytesIO

import pytest

from test.offline.web_fixture_app import (
    build_fixture_tree,
    find_item,
    json_text,
    make_app,
    make_client,
    require_web,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def web_client(tmp_path):
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    app = make_app(web, tree)
    return tree, make_client(app)


def _history(client, **params):
    response = client.get("/api/history", params={"limit": 50, **params})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload.get("items"), list)
    assert "next_cursor" in payload
    return payload


def _all_items(client, **params):
    items = []
    cursor = None
    while True:
        query = {"limit": 50, **params}
        if cursor:
            query["cursor"] = cursor
        page = _history(client, **query)
        items.extend(page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            return items


def test_history_lists_run_saved_backtest_and_decision_sources(web_client):
    tree, client = web_client
    items = _all_items(client)
    sources = {item["source"] for item in items}
    assert {"run", "saved", "backtest", "decision"} <= sources

    for item in items:
        assert item["artifact_id"]
        assert re.fullmatch(r"[0-9a-f]{16}", item["artifact_id"])
        assert "path" not in item
        assert "absolute_path" not in item
        assert str(tree.results_dir) not in json.dumps(item)
        assert str(tree.root) not in json.dumps(item)


def test_history_pagination_returns_disjoint_pages(web_client):
    _, client = web_client
    first = _history(client, limit=2)
    assert len(first["items"]) == 2
    assert first["next_cursor"]

    second = _history(client, limit=2, cursor=first["next_cursor"])
    first_ids = {item["artifact_id"] for item in first["items"]}
    second_ids = {item["artifact_id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_run_detail_exposes_sections_rating_and_no_path(web_client):
    tree, client = web_client
    item = find_item(_all_items(client), "run", "NVDA")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["rating"] == "Buy"
    assert payload["review"] is False
    assert "market_report" in payload["sections"]
    assert "final_trade_decision" in payload["sections"]
    assert str(tree.run_dir) not in response.text
    assert str(tree.results_dir) not in response.text


def test_saved_report_detail_exposes_complete_artifact(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "saved", "AAPL")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["sections"]
    complete = [a for a in payload["artifacts"] if a.get("kind") == "complete"]
    assert complete, payload["artifacts"]


def test_backtest_detail_exposes_structured_summary_without_log_path(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "backtest")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    payload = response.json()
    summary = payload.get("summary", payload)

    assert "resolved" in summary
    assert "pending" in summary
    assert "by_rating" in summary
    assert "log_path" not in response.text


def test_decision_memory_detail_is_read_only_entries(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "decision")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    payload = response.json()

    entries = payload["entries"]
    assert entries
    entry = entries[0]
    assert {"ticker", "rating", "pending", "decision"} <= set(entry)
    assert entry["ticker"] in {"MSFT"}


def test_download_complete_markdown(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "saved", "AAPL")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "complete"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Trading Analysis Report: AAPL" in response.text


def test_download_archive_zip(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] in {
        "application/zip",
        "application/x-zip-compressed",
    }
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
    assert names
    assert any(name.endswith(".md") for name in names)


def test_download_single_section(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download",
        params={"kind": "section", "section": "market_report"},
    )
    assert response.status_code == 200, response.text
    assert "MKT content" in response.text


def test_missing_complete_report_is_not_synthesized(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "run", "NVDA")
    complete = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "complete"}
    )
    assert complete.status_code == 404, complete.text

    archive = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
    )
    assert archive.status_code == 200, archive.text


def test_partial_run_is_reported_as_partial(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "run", "MSFT")
    assert item["status"] == "partial"


def test_malformed_state_log_is_ignored(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "run", "NVDA")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    assert "MKT content" in json_text(response)


def test_unknown_artifact_id_returns_404(web_client):
    _, client = web_client
    response = client.get("/api/history/0000000000000000")
    assert response.status_code == 404
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "bad_id",
    [
        "..",
        "../etc/passwd",
        "%2e%2e%2fetc%2fpasswd",
        "/etc/passwd",
        "..%5cetc%5cpasswd",
    ],
)
def test_path_traversal_is_rejected(web_client, bad_id):
    _, client = web_client
    response = client.get(f"/api/history/{bad_id}")
    assert response.status_code in {400, 404}, response.text
    assert "root:" not in response.text


def test_unknown_download_kind_and_section_are_rejected(web_client):
    _, client = web_client
    item = find_item(_all_items(client), "run", "NVDA")
    bad_kind = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "exe"}
    )
    assert bad_kind.status_code in {400, 404, 422}
    bad_section = client.get(
        f"/api/history/{item['artifact_id']}/download",
        params={"kind": "section", "section": "../../etc/passwd"},
    )
    assert bad_section.status_code in {400, 404, 422}


def test_history_endpoints_are_read_only(web_client):
    tree, client = web_client
    before = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tree.root.rglob("*")
        if path.is_file()
    }
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/history")
        assert response.status_code in {404, 405}
    after = {
        path: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tree.root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_history_creates_no_index_database_or_extra_files(web_client):
    tree, client = web_client
    before = {path for path in tree.root.rglob("*") if path.is_file()}
    _all_items(client)
    after = {path for path in tree.root.rglob("*") if path.is_file()}
    assert after == before
    assert not list(tree.root.rglob("*.db"))
    assert not list(tree.root.rglob("*.sqlite"))
