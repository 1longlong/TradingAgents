"""Read-only configuration projection for the analysis wizard."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Query

from cli.prefs import load_last_run
from cli.utils import _llm_provider_table
from tradingagents.default_config import _ENV_OVERRIDES, DEFAULT_CONFIG, _apply_env_overrides
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV, get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
from tradingagents_web.errors import error_response

router = APIRouter(prefix="/api", tags=["config"])

_REMEMBERED_KEYS = (
    "output_language",
    "analysts",
    "research_depth",
    "llm_provider",
    "quick_think_llm",
    "deep_think_llm",
)


def effective_defaults() -> dict:
    """Project server configuration without changing core state (REQ-WEB-013)."""
    return _apply_env_overrides(deepcopy(DEFAULT_CONFIG))


def _key_status() -> dict[str, str]:
    providers = {key for _, key, _ in _llm_provider_table()} | set(PROVIDER_API_KEY_ENV)
    status: dict[str, str] = {}
    for provider in sorted(providers):
        env_var = get_api_key_env(provider)
        spec = OPENAI_COMPATIBLE_PROVIDERS.get(provider)
        if env_var is None or (spec and spec.key_optional and not os.environ.get(env_var)):
            status[provider] = "not_required"
        elif os.environ.get(env_var):
            status[provider] = "configured"
        else:
            status[provider] = "not_configured"
    return status


@router.get("/config")
def config() -> dict:
    prefs = load_last_run()
    defaults = effective_defaults()
    providers = [
        {"key": key, "label": label, "default_url": url}
        for label, key, url in _llm_provider_table()
    ]
    offered = {item["key"] for item in providers}
    providers.extend(
        {"key": key, "label": f"{key.removesuffix('-cn').upper()} (China)", "default_url": None}
        for key in PROVIDER_API_KEY_ENV
        if key not in offered
    )
    return {
        "defaults": {
            "llm_provider": defaults.get("llm_provider", "openai"),
            "quick_think_llm": defaults.get("quick_think_llm"),
            "deep_think_llm": defaults.get("deep_think_llm"),
            "output_language": defaults.get("output_language", "English"),
            "analysts": ["market", "social", "news", "fundamentals"],
            "research_depth": defaults.get("max_debate_rounds", 1),
            "checkpoint": defaults.get("checkpoint_enabled", False),
        },
        "backend_url_configured": bool(defaults.get("backend_url")),
        "providers": providers,
        "env_locks": {
            key: bool(os.environ.get(env_var)) for env_var, key in _ENV_OVERRIDES.items()
        },
        "key_status": _key_status(),
        "prefs": {key: prefs[key] for key in _REMEMBERED_KEYS if key in prefs},
    }


@router.get("/config/models")
def models(
    provider: str = Query(...),
    mode: str = Query(...),
) -> Any:
    if mode not in {"quick", "deep"}:
        return error_response(422, "validation", "mode must be quick or deep")
    try:
        options = get_model_options(provider, mode)
    except KeyError:
        known = {key for _, key, _ in _llm_provider_table()} | set(PROVIDER_API_KEY_ENV)
        if provider.lower() not in known:
            return error_response(422, "validation", "unknown provider")
        # Existing providers such as Azure use deployment IDs, not a fixed catalog.
        options = [("Custom model ID", "custom")]
    rendered = [{"value": value, "label": label} for label, value in options]
    if not any(item["value"] == "custom" for item in rendered):
        rendered.append({"value": "custom", "label": "Custom model ID"})
    return {"models": rendered}
