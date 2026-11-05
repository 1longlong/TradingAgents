"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from tradingagents_web import __version__

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "active_run_id": None,
    }
