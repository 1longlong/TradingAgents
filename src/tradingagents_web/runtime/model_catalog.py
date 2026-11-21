"""REQ-WEB-001/013, ADR-001-choice: bounded public OpenRouter discovery."""

from __future__ import annotations

import json
import math
import re
import threading
import time

import requests

from cli.utils import _OPENROUTER_MAINSTREAM

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_MAX_BYTES = 2_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{0,255}")


def _without_auth(request):
    """Suppress requests' implicit netrc lookup while retaining proxy routing."""
    return request


class OpenRouterCatalog:
    """Application-local cache; never accepts URLs or credentials from clients."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.items: list[dict[str, str]] = []
        self.attempted_at: float | None = None
        self.warning: str | None = None

    def models(self, *, refresh: bool = False) -> dict:
        with self.lock:
            age = None if self.attempted_at is None else self.clock() - self.attempted_at
            ttl = 5 if self.warning else 300
            if age is None or (age >= 2 and (refresh or age >= ttl)):
                try:
                    self.items = self._fetch()
                    self.warning = None
                except (requests.RequestException, ValueError, TypeError):
                    self.warning = (
                        "Model list unavailable; showing cached suggestions. You can still enter a model ID."
                        if self.items
                        else "OpenRouter model list is unavailable. Enter a model ID manually."
                    )
                self.attempted_at = self.clock()
            return {
                "models": [dict(item) for item in self.items]
                + [{"value": "custom", "label": "Custom model ID"}],
                "source": "openrouter" if not self.warning else "cache" if self.items else "custom",
                **({"warning": self.warning} if self.warning else {}),
            }

    @staticmethod
    def _fetch() -> list[dict[str, str]]:
        # No authentication or user endpoint is forwarded to this fixed public URL.
        with requests.get(
            _MODELS_URL, timeout=10, stream=True, allow_redirects=False, auth=_without_auth
        ) as response:
            if response.status_code != 200:
                raise ValueError("model discovery failed")
            data = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                data.extend(chunk)
                if len(data) > _MAX_BYTES:
                    raise ValueError("model catalogue exceeds response limit")
            payload = json.loads(data)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("invalid model catalogue")
        candidates = []
        for item in payload["data"]:
            if not isinstance(item, dict):
                continue
            mid = item.get("id")
            if not isinstance(mid, str) or not _ID.fullmatch(mid) or mid == "custom":
                continue
            architecture = item.get("architecture")
            outputs = (
                architecture.get("output_modalities") if isinstance(architecture, dict) else None
            )
            if isinstance(outputs, list) and "text" not in outputs:
                continue
            created = item.get("created", 0)
            if (
                isinstance(created, bool)
                or not isinstance(created, (int, float))
                or not math.isfinite(created)
            ):
                created = 0
            name = item.get("name")
            label = (
                name
                if isinstance(name, str)
                and 0 < len(name) <= 256
                and not any(ord(c) < 32 for c in name)
                else mid
            )
            candidates.append((created, {"value": mid, "label": label}))
        candidates.sort(key=lambda item: item[0], reverse=True)
        mainstream = [
            item
            for item in candidates
            if item[1]["value"].split("/", 1)[0] in _OPENROUTER_MAINSTREAM
        ]
        items: dict[str, dict[str, str]] = {}
        for _, item in mainstream or candidates:
            items.setdefault(item["value"], item)
        if not items:
            raise ValueError("empty model catalogue")
        return list(items.values())[:5]
