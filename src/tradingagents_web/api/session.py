"""Per-process CSRF token for state-changing requests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from tradingagents_web import __version__

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/session")
def session(request: Request) -> dict:
    return {
        "csrf_token": request.app.state.csrf_token,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
    }
