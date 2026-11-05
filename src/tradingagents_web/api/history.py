"""Read-only history, report detail, and download endpoints."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from tradingagents_web.artifacts.downloads import (
    ArtifactUnavailable,
    FileTooLarge,
    archive_bytes,
    complete_report,
    read_text,
    section_file,
)
from tradingagents_web.artifacts.index import ArtifactIndex
from tradingagents_web.artifacts.readers import detail
from tradingagents_web.errors import error_response
from tradingagents_web.security import (
    collect_secrets,
    redact_obj,
    redact_text,
)

router = APIRouter(prefix="/api", tags=["history"])

_ARTIFACT_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _settings(request: Request):
    return request.app.state.settings


def _index(request: Request) -> ArtifactIndex:
    return ArtifactIndex(_settings(request))


def _secrets() -> tuple[str, ...]:
    return collect_secrets()


@router.get("/history")
def list_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
) -> Any:
    items = _index(request).scan()
    if ticker:
        needle = ticker.lower()
        items = [item for item in items if needle in item.ticker.lower()]
    if source:
        items = [item for item in items if item.source == source]

    offset = 0
    if cursor:
        try:
            offset = int(cursor)
        except ValueError:
            return error_response(400, "validation", "cursor must be an integer offset")
        if offset < 0:
            return error_response(400, "validation", "cursor must be non-negative")

    page = items[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(items) else None
    secrets = _secrets()
    return {
        "items": [redact_obj(item.to_item(), secrets) for item in page],
        "next_cursor": next_cursor,
    }


@router.get("/history/{artifact_id}")
def history_detail(request: Request, artifact_id: str) -> Any:
    if not _ARTIFACT_ID_RE.fullmatch(artifact_id):
        return error_response(404, "not_found", "artifact not found")
    artifact = _index(request).find(artifact_id)
    if artifact is None:
        return error_response(404, "not_found", "artifact not found")
    return redact_obj(detail(artifact), _secrets())


@router.get("/history/{artifact_id}/download")
def history_download(
    request: Request,
    artifact_id: str,
    kind: str = Query(...),
    section: str | None = None,
) -> Response:
    if not _ARTIFACT_ID_RE.fullmatch(artifact_id):
        return error_response(404, "not_found", "artifact not found")
    artifact = _index(request).find(artifact_id)
    if artifact is None:
        return error_response(404, "not_found", "artifact not found")

    settings = _settings(request)
    secrets = _secrets()
    try:
        if kind == "complete":
            path = complete_report(artifact)
            text = redact_text(read_text(path, settings.max_report_bytes), secrets)
            return Response(
                content=text,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{_filename(artifact, "complete.md")}"'
                },
            )
        if kind == "section":
            if not section:
                return error_response(400, "validation", "section is required")
            path = section_file(artifact, section)
            text = redact_text(read_text(path, settings.max_report_bytes), secrets)
            return Response(
                content=text,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{_filename(artifact, "section.md")}"'
                },
            )
        if kind == "archive":
            payload = archive_bytes(
                artifact,
                settings.max_zip_bytes,
                lambda text: redact_text(text, secrets),
            )
            return Response(
                content=payload,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{_filename(artifact, "report.zip")}"'
                },
            )
    except FileTooLarge:
        return error_response(413, "storage", "requested artifact exceeds the response limit")
    except ArtifactUnavailable:
        return error_response(404, "not_found", "artifact is not available")
    return error_response(400, "validation", "unsupported download kind")


def _filename(artifact, suffix: str) -> str:
    base = f"{artifact.ticker}_{artifact.date or 'run'}_{suffix}"
    return _SAFE_FILENAME_RE.sub("_", base)
