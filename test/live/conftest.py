"""Opt-in live test configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass

_LIVE_PROVIDER_KEYS = (
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("xai", "XAI_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("dashscope", "DASHSCOPE_API_KEY"),
    ("zhipu", "ZHIPU_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
)

if not os.environ.get("TRADINGAGENTS_LLM_PROVIDER"):
    for _provider, _env_name in _LIVE_PROVIDER_KEYS:
        _key = os.environ.get(_env_name, "").strip()
        if _key and _key != "placeholder":
            os.environ["TRADINGAGENTS_LLM_PROVIDER"] = _provider
            if _provider == "deepseek":
                os.environ.setdefault(
                    "TRADINGAGENTS_DEEP_THINK_LLM",
                    "deepseek-chat",
                )
                os.environ.setdefault(
                    "TRADINGAGENTS_QUICK_THINK_LLM",
                    "deepseek-chat",
                )
            break


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LIVE_TRADING_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="set RUN_LIVE_TRADING_TESTS=1 to run live trading tests"
    )
    for item in items:
        item.add_marker(skip)
