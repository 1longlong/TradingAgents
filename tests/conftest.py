"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        # `or` not a .get default: an env var present but empty (e.g. a key left
        # blank in a .env copied from .env.example) must still get the placeholder.
        monkeypatch.setenv(env_var, os.environ.get(env_var) or "placeholder")


@pytest.fixture(autouse=True)
def _isolate_config():
    """Reset the global dataflows config before and after each test.

    ``set_config`` merges (it never clears keys absent from the override), so a
    test that sets e.g. ``tool_vendors`` would otherwise leak into later tests
    and make routing behavior order-dependent. Replace the global outright so
    every test starts from a clean DEFAULT_CONFIG.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


#: Network endpoints tests must never reach for real. The default ``get_news``
#: chain now tries Alpha Vantage and GDELT before yfinance; without this guard
#: those are live HTTP calls, which makes results depend on the network and on
#: whatever key happens to be in the environment (and risks scraping history
#: with a real credential during a test run).
_LIVE_NETWORK_HOSTS = (
    "alpha_vantage",
    "alphavantage",
    "api.gdeltproject.org",
    "gdelttopics",
)


@pytest.fixture(autouse=True)
def _block_live_news_vendors(monkeypatch):
    """Make the news vendors fail fast instead of dialling out.

    The default ``get_news`` chain is now
    ``alpha_vantage_historical,gdelt,yfinance``. Without this, a test that only
    patches the yfinance transport would still make a **real** Alpha Vantage or
    GDELT request first (locally with a real key), so results would depend on
    the network and on the environment. Both are patched here to raise typed
    vendor errors, which the router already handles by skipping to the next
    vendor -- exactly what would happen in production on such a failure.

    Tests that exercise these adapters patch their internals themselves, which
    overrides this fixture.
    """

    import tradingagents.dataflows.historical_news as hist

    def _refuse_alpha(*_args, **_kwargs):
        raise OSError("live Alpha Vantage disabled in tests")

    monkeypatch.setattr(hist, "_alpha_vantage_news", _refuse_alpha)

    import tradingagents.dataflows.gdelt_news as gdelt

    monkeypatch.setattr(gdelt, "_request", lambda *a, **k: (None, None, "transport"))
    monkeypatch.setattr(gdelt, "_fetch_page", lambda *a, **k: (None, None, "transport"))


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
