"""Checkpoint clearing with explicit confirmation and a single-run guard."""

from __future__ import annotations

from fastapi import APIRouter, Request

from tradingagents.graph.checkpointer import clear_all_checkpoints
from tradingagents_web.errors import error_response
from tradingagents_web.models.requests import CheckpointClearRequest

router = APIRouter(prefix="/api", tags=["checkpoints"])


@router.post("/checkpoints/clear")
def clear_checkpoints(request: Request, body: CheckpointClearRequest):
    if body.confirm != "CLEAR":
        return error_response(422, "validation", "confirm must be the word CLEAR")
    if request.app.state.coordinator.active_snapshot() is not None:
        return error_response(409, "conflict", "a run is active")
    cleared = clear_all_checkpoints(request.app.state.settings.data_cache_dir)
    return {"cleared": cleared}
