"""Safe error payloads for the WebUI.

Errors never include stack traces, absolute paths, or credential values.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.responses import JSONResponse


def error_payload(category: str, message: str, **fields) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "category": category,
            "message": message,
            "correlation_id": f"c_{uuid.uuid4().hex[:12]}",
        }
    }
    if fields:
        payload["error"]["fields"] = fields
    return payload


def error_response(status_code: int, category: str, message: str, **fields) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(category, message, **fields),
    )
