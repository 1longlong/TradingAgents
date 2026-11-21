"""Small outbound-HTTP safety helpers shared by news vendors.

The validator callbacks live with each vendor because their trust boundaries
differ; this module only ensures redirects are validated *before* the next
request is made. It does not replace DNS/TLS validation in the vendor module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SafeRedirectHandler(HTTPRedirectHandler):
    """Reject an unsafe redirect target before the client contacts it."""

    def __init__(self, validate: Callable[[str], None]) -> None:
        super().__init__()
        self._validate = validate

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        # This callback runs before urllib issues the redirected request, so a
        # loopback/private target is never contacted.
        self._validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(request: Request, *, timeout: float, validate: Callable[[str], None]):
    """Open ``request`` with redirect targets validated before following."""
    opener = build_opener(SafeRedirectHandler(validate))
    return opener.open(request, timeout=timeout)
