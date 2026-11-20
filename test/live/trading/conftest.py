"""Live-test fixtures with process-local proxy and credential isolation."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "dashscope_cn": "DASHSCOPE_CN_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}


def _env_or_file(name: str, values: dict[str, str | None]) -> str:
    return (os.environ.get(name) or values.get(name) or "").strip()


@pytest.fixture()
def live_config(monkeypatch):
    """Load .env, choose a provider, and set the yfinance proxy only for this test."""
    try:
        from dotenv import dotenv_values, load_dotenv
    except ImportError:
        pytest.skip("python-dotenv is not installed")

    load_dotenv(REPO_ROOT / ".env", override=False)
    values = dotenv_values(REPO_ROOT / ".env")

    from tradingagents.default_config import DEFAULT_CONFIG

    provider = _env_or_file("TRADINGAGENTS_LLM_PROVIDER", values).lower()
    if not provider:
        for candidate, env_name in _PROVIDER_KEYS.items():
            key = _env_or_file(env_name, values)
            if key and key != "placeholder":
                provider = candidate
                break

    if not provider:
        pytest.skip("no real LLM API key configured for the selected provider")

    if provider == "openai_compatible":
        if not _env_or_file("TRADINGAGENTS_LLM_BACKEND_URL", values):
            pytest.skip("openai_compatible requires TRADINGAGENTS_LLM_BACKEND_URL")
    elif provider != "ollama":
        env_name = _PROVIDER_KEYS.get(provider)
        key = _env_or_file(env_name, values) if env_name else ""
        if not key or key == "placeholder":
            pytest.skip("no real LLM API key configured for the selected provider")
        monkeypatch.setenv(env_name, key)

    deep_model = _env_or_file("TRADINGAGENTS_DEEP_THINK_LLM", values)
    quick_model = _env_or_file("TRADINGAGENTS_QUICK_THINK_LLM", values)
    if provider == "deepseek":
        deep_model = deep_model or "deepseek-chat"
        quick_model = quick_model or "deepseek-chat"
    deep_model = deep_model or DEFAULT_CONFIG["deep_think_llm"]
    quick_model = quick_model or DEFAULT_CONFIG["quick_think_llm"]

    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", provider)
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_LLM", deep_model)
    monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_LLM", quick_model)

    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "llm_provider": provider,
            "deep_think_llm": deep_model,
            "quick_think_llm": quick_model,
        }
    )

    proxy = _env_or_file("TRADINGAGENTS_LIVE_PROXY", values) or "http://127.0.0.1:7897"
    import yfinance as yf

    previous_proxy = yf.config.network.proxy
    try:
        yf.config.network.proxy = proxy
    except AttributeError:
        yf.set_config(proxy=proxy)
    try:
        yield config
    finally:
        yf.config.network.proxy = previous_proxy
