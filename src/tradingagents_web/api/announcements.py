"""Server-side announcement fetch with a short cache and safe fallback."""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, Request

from cli.announcements import fetch_announcements
from cli.config import CLI_CONFIG

router = APIRouter(prefix="/api", tags=["announcements"])

CACHE_SECONDS = 60.0
_RICH_TAG_RE = re.compile(r"\[/?[A-Za-z][^\]]*\]")


def _fallback_text() -> str:
    return _RICH_TAG_RE.sub("", str(CLI_CONFIG["announcements_fallback"])).strip()


def _normalise(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("announcement payload must be an object")
    raw = data.get("announcements")
    if not isinstance(raw, list):
        raise ValueError("announcements must be a list")
    announcements = [str(item) for item in raw if isinstance(item, str) and item]
    return {
        "announcements": announcements or [_fallback_text()],
        "require_attention": bool(data.get("require_attention", False)),
    }


@router.get("/announcements")
def get_announcements(request: Request):
    cached = getattr(request.app.state, "announcement_cache", None)
    now = time.monotonic()
    if cached is not None and now - cached["at"] < CACHE_SECONDS:
        return cached["data"]

    try:
        payload = _normalise(fetch_announcements(timeout=1.0))
    except Exception:
        payload = {
            "announcements": [_fallback_text()],
            "require_attention": False,
        }
    request.app.state.announcement_cache = {"at": now, "data": payload}
    return payload
