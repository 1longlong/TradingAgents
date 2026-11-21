"""Security helpers: Host validation, CSP headers, and secret redaction.

The WebUI is loopback-only and has no authentication. Host/origin checks and a
strict CSP are the compensating controls. Artifact text is redacted for exact
values of credential-like environment variables before it is returned.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

_SECRET_ENV_RE = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)$", re.I)
_MIN_REDACT_LEN = 12


def host_allowed(host_header: str | None) -> bool:
    """Allow only loopback Host headers, with or without a port."""
    if not host_header:
        return False
    host = host_header.strip()
    if host.startswith("["):
        # IPv6 form: [::1]:8000
        host = host.split("]", 1)[0].removeprefix("[")
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host.lower() in {"127.0.0.1", "localhost"}


CSRF_HEADER = "x-csrf-token"
_CSRF_EXACT = {
    "/api/runs",
    "/api/simulation/account",
    "/api/simulation/decisions",
    "/api/simulation/jobs",
    "/api/backtests",
    "/api/checkpoints/clear",
    "/api/portfolio/validate",
}
_CSRF_CANCEL_RE = re.compile(r"^/api/runs/[^/]+/cancel$")


def csrf_path(path: str) -> bool:
    """Only real state-changing endpoints require a CSRF token.

    Unknown POST routes must still reach FastAPI and return 404/405; otherwise
    a generic CSRF middleware would mask them as 403.
    """
    return (
        path in _CSRF_EXACT
        or bool(_CSRF_CANCEL_RE.fullmatch(path))
        or bool(re.fullmatch(r"/api/simulation/approvals/[^/]+", path))
    )


def origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }


def security_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "X-Frame-Options": "DENY",
    }


def collect_secrets(environ: dict[str, str] | None = None) -> tuple[str, ...]:
    """Collect exact credential-like values for response redaction.

    Short values are ignored to avoid redacting ordinary words. This is a
    best-effort boundary, not a substitute for not putting secrets in artifacts.
    """
    source = environ if environ is not None else os.environ
    secrets = {
        value
        for name, value in source.items()
        if value and len(value) >= _MIN_REDACT_LEN and _SECRET_ENV_RE.search(name)
    }
    return tuple(sorted(secrets, key=len, reverse=True))


def redact_text(text: str, secrets: tuple[str, ...] | None = None) -> str:
    if not text:
        return text
    for secret in secrets if secrets is not None else collect_secrets():
        if secret and secret in text:
            text = text.replace(secret, "***")
    return text


def redact_obj(value: Any, secrets: tuple[str, ...] | None = None) -> Any:
    """Recursively redact strings in JSON-compatible data."""
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, dict):
        return {key: redact_obj(child, secrets) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_obj(child, secrets) for child in value]
    if isinstance(value, tuple):
        return [redact_obj(child, secrets) for child in value]
    return value
