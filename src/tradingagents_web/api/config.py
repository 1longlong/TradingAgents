"""Read-only configuration projection for the analysis wizard."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Query

from cli.prefs import load_last_run
from cli.utils import _llm_provider_table
from tradingagents.default_config import _ENV_OVERRIDES, DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV, get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options
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


def _key_status() -> dict[str, str]:
    providers = {key for _, key, _ in _llm_provider_table()} | set(PROVIDER_API_KEY_ENV)
    status: dict[str, str] = {}
    for provider in sorted(providers):
        env_var = get_api_key_env(provider)
        if env_var is None:
            status[provider] = "not_required"
        elif os.environ.get(env_var):
            status[provider] = "configured"
        else:
            status[provider] = "not_configured"
    return status


@router.get("/config")
def config() -> dict:
    prefs = load_last_run()
    return {
        "defaults": {
            "llm_provider": DEFAULT_CONFIG.get("llm_provider", "openai"),
            "quick_think_llm": DEFAULT_CONFIG.get("quick_think_llm"),
            "deep_think_llm": DEFAULT_CONFIG.get("deep_think_llm"),
            "output_language": DEFAULT_CONFIG.get("output_language", "English"),
            "analysts": ["market", "social", "news", "fundamentals"],
            "research_depth": DEFAULT_CONFIG.get("max_debate_rounds", 1),
        },
        "providers": [
            {"key": key, "label": label, "default_url": url}
            for label, key, url in _llm_provider_table()
        ],
        "env_locks": {
            key: bool(os.environ.get(env_var))
            for env_var, key in _ENV_OVERRIDES.items()
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
        return error_response(422, "validation", "unknown provider")
    rendered = [{"value": value, "label": label} for label, value in options]
    if not any(item["value"] == "custom" for item in rendered):
        rendered.append({"value": "custom", "label": "Custom model ID"})
    return {"models": rendered}
