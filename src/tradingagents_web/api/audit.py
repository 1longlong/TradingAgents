"""Audit read API: REQ-WEB-008/009/024, ADR-002, INV-WEB-003/004/005/014."""

from __future__ import annotations

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from tradingagents_web.artifacts.audit import audit_artifact, audit_view
from tradingagents_web.artifacts.downloads import ArtifactUnavailable, FileTooLarge
from tradingagents_web.artifacts.index import ArtifactIndex
from tradingagents_web.errors import error_response

router = APIRouter(prefix="/api", tags=["audit"])
_ARTIFACT_ID = re.compile(r"[0-9a-f]{16}")
_RUN_ID = re.compile(r"r_[0-9a-f]{12}")


def _find(request: Request, artifact_id: str):
    if not _ARTIFACT_ID.fullmatch(artifact_id):
        return None
    return ArtifactIndex(request.app.state.settings).find(artifact_id)


def _view(request: Request, artifact, *, run_status: str | None = None):
    if artifact is None:
        return error_response(404, "not_found", "analysis artifact not found")
    try:
        projected = audit_view(artifact, request.app.state.settings)
        if run_status is not None:
            projected["status"] = run_status
        return JSONResponse(projected)
    except FileTooLarge:
        return error_response(413, "storage", "audit exceeds the response limit")
    except ArtifactUnavailable:
        return error_response(404, "not_found", "analysis audit is unavailable")


@router.get("/history/{artifact_id}/audit")
def history_audit(request: Request, artifact_id: str):
    return _view(request, _find(request, artifact_id))


@router.get("/runs/{run_id}/audit")
def run_audit(request: Request, run_id: str):
    if not _RUN_ID.fullmatch(run_id):
        return error_response(404, "not_found", "run not found")
    record = request.app.state.coordinator.get(run_id)
    if record is None:
        return error_response(404, "not_found", "run not found")
    if not record.artifact_id:
        snapshot = record.to_snapshot()
        return {
            "schema_version": "1.0",
            "run_id": run_id,
            "available": False,
            "ticker": snapshot["ticker"],
            "trade_date": snapshot["trade_date"],
            "status": snapshot["status"],
            "artifact_availability": "absent",
            "artifacts": [],
            "data": {},
            "sanitized": True,
        }
    return _view(
        request, _find(request, record.artifact_id), run_status=record.to_snapshot()["status"]
    )


@router.get("/history/{artifact_id}/audit/artifacts/{kind}")
def family(request: Request, artifact_id: str, kind: str, download: bool = False):
    artifact = _find(request, artifact_id)
    if artifact is None:
        return error_response(404, "not_found", "analysis artifact not found")
    try:
        content, media, filename = audit_artifact(artifact, request.app.state.settings, kind)
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else {}
        return Response(content, media_type=media, headers=headers)
    except FileTooLarge:
        return error_response(413, "storage", "audit exceeds the response limit")
    except ArtifactUnavailable:
        return error_response(404, "not_found", "audit artifact is unavailable")
    except ValueError:
        return error_response(422, "storage", "audit artifact is invalid")
