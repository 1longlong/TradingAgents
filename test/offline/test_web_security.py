"""WebUI permission and secret boundaries.

Covers REQ-WEB-020 (loopback/no auth), REQ-WEB-023 (secrets), REQ-WEB-024
(no paths), REQ-WEB-025 (untrusted-content policy) and
INV-WEB-002/003/004/005/012/013. Server-only key status is deferred to the
configuration/wizard iteration and is not claimed here.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

import pytest

from test.offline.web_fixture_app import (
    SECRET,
    build_fixture_tree,
    find_item,
    json_text,
    make_app,
    make_client,
    require_web,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def web_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    app = make_app(web, tree)
    return tree, make_client(app)


def _items(client):
    response = client.get("/api/history", params={"limit": 50})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_bind_address_is_loopback_only(tmp_path):
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    with pytest.raises((ValueError, RuntimeError)):
        make_app(web, tree, host="0.0.0.0")


def test_non_loopback_host_header_is_rejected(web_client):
    _, client = web_client
    response = client.get("/api/health", headers={"Host": "evil.example"})
    assert response.status_code == 400, response.text


def test_localhost_host_header_is_allowed(web_client):
    _, client = web_client
    response = client.get("/api/health", headers={"Host": "localhost:8000"})
    assert response.status_code == 200, response.text


def test_no_wildcard_cors(web_client):
    _, client = web_client
    response = client.options(
        "/api/history",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "*"
    assert allow_origin in {None, ""} or response.status_code in {403, 405}


def test_csp_and_security_headers(web_client):
    _, client = web_client
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    csp = response.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src" in csp
    assert "unsafe-eval" not in csp
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("referrer-policy") == "no-referrer"


def test_no_authentication_is_required_on_loopback(web_client):
    _, client = web_client
    response = client.get("/api/history")
    assert response.status_code == 200, response.text
    assert "www-authenticate" not in response.headers


def test_secrets_never_serialized(web_client):
    _, client = web_client
    for response in (
        client.get("/api/health"),
        client.get("/api/history"),
        client.get("/api/history/0000000000000000"),
        client.get("/openapi.json"),
    ):
        assert SECRET not in response.text


def test_secret_is_redacted_from_artifact_downloads(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download",
        params={"kind": "section", "section": "market_report"},
    )
    assert response.status_code == 200, response.text
    assert SECRET not in response.text
    assert "***" in response.text or "[REDACTED]" in response.text


def test_secret_is_redacted_inside_archive(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8", errors="ignore")
            assert SECRET not in text, name


def test_responses_contain_no_filesystem_paths(web_client):
    tree, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    responses = [
        client.get("/api/history"),
        client.get(f"/api/history/{item['artifact_id']}"),
        client.get(
            f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
        ),
    ]
    for response in responses:
        assert str(tree.root) not in response.text
        assert str(tree.results_dir) not in response.text
        assert "/Users/" not in response.text
        assert "/private/" not in response.text


def test_archive_entries_are_relative_and_do_not_escape(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download", params={"kind": "archive"}
    )
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        for name in archive.namelist():
            assert not name.startswith("/")
            assert ".." not in name.split("/")
            assert "\\" not in name


def test_artifact_ids_are_opaque(web_client):
    _, client = web_client
    ids = [item["artifact_id"] for item in _items(client)]
    assert ids
    assert all(re.fullmatch(r"[0-9a-f]{16}", value) for value in ids)


@pytest.mark.parametrize(
    "path",
    ["/api/orders", "/api/trades", "/api/execute", "/api/positions"],
)
def test_no_execution_endpoint_exists(web_client, path):
    _, client = web_client
    response = client.post(path, json={})
    assert response.status_code in {404, 405}


def test_history_mutations_are_rejected(web_client):
    _, client = web_client
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/history")
        assert response.status_code in {404, 405}


def test_errors_are_redacted(web_client):
    tree, client = web_client
    response = client.get("/api/history/does-not-exist")
    assert response.status_code == 404
    assert SECRET not in response.text
    assert str(tree.results_dir) not in response.text
    assert "Traceback" not in response.text


def test_oversized_report_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    web = require_web()
    app = make_app(web, tree, max_report_bytes=10)
    client = make_client(app)
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(
        f"/api/history/{item['artifact_id']}/download",
        params={"kind": "section", "section": "market_report"},
    )
    assert response.status_code == 413, response.text


def test_missing_static_assets_fail_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    tree = build_fixture_tree(tmp_path)
    empty_static = tmp_path / "empty-static"
    empty_static.mkdir()
    web = require_web()
    app = make_app(web, tree, static_dir=empty_static)
    client = make_client(app)
    response = client.get("/")
    assert response.status_code in {404, 503}, response.text
    body = response.text.lower()
    assert "build" in body or "frontend" in body
    assert client.get("/api/health").status_code == 200


def test_openapi_has_history_and_no_execution_paths(web_client):
    _, client = web_client
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = response.json()["paths"]
    assert "/api/history" in paths
    assert "/api/history/{artifact_id}" in paths
    forbidden = ("order", "trade", "execute", "position")
    assert not any(
        any(word in path.lower() for word in forbidden) for path in paths
    ), paths


def test_history_json_contains_no_secret_after_detail(web_client):
    _, client = web_client
    item = find_item(_items(client), "run", "NVDA")
    response = client.get(f"/api/history/{item['artifact_id']}")
    assert response.status_code == 200, response.text
    assert SECRET not in json_text(response)
