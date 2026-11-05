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


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client


# --- Yahoo error-classification helpers ------------------------------------
# Shared by test_yahoo_error_classifier.py, test_yahoo_error_paths.py and
# test_yahoo_empty_and_internal.py. Exposed as a fixture so those modules do not
# need the tests directory to be importable as a package.


class _YahooHelpers:
    """Network-free builders for Yahoo failure scenarios."""

    @staticmethod
    def status_error(client, status):
        """An ``HTTPError`` as ``client`` raises it, carrying ``status``.

        ``requests`` computes the status from ``status_code``; curl_cffi also
        consults a plain ``ok`` attribute, which defaults to True on an empty
        response object, so it is set explicitly there.
        """
        response = client.models.Response()
        response.status_code = status
        response.url = "https://query2.finance.yahoo.com/v8/finance/chart/AAPL"
        if hasattr(response, "ok") and not hasattr(type(response), "ok"):
            response.ok = status < 400
        try:
            response.raise_for_status()
        except client.exceptions.HTTPError as exc:
            return exc
        raise AssertionError(f"client {client.__name__} did not raise for {status}")

    @staticmethod
    def ticker_raising(exc):
        """A yfinance.Ticker stand-in whose every data attribute raises ``exc``."""

        class RaisingTicker:
            def __init__(self, symbol):
                pass

            def __getattr__(self, name):
                if name.startswith("__"):
                    raise AttributeError(name)
                raise exc
        return RaisingTicker

    @staticmethod
    def ticker_returning(frame, news=None):
        """A ticker stand-in returning ``frame`` from every data attribute."""

        class StubTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def __getattr__(self, name):
                if name.startswith("__"):
                    raise AttributeError(name)
                if name == "get_news":
                    return lambda count: news if news is not None else []
                return frame

        return StubTicker(None)

    @staticmethod
    def search_raising(exc):
        def factory(*a, **k):
            raise exc

        return factory

    @staticmethod
    def curl_requests():
        from curl_cffi import requests as curl_client

        return curl_client


@pytest.fixture()
def yahoo():
    return _YahooHelpers()


@pytest.fixture()
def no_retry(monkeypatch):
    """Run the wrapped call once so the injected exception is what surfaces."""
    import tradingagents.dataflows.y_finance as y_finance
    import tradingagents.dataflows.yfinance_news as yfinance_news

    monkeypatch.setattr(y_finance, "yf_retry", lambda fn: fn())
    monkeypatch.setattr(yfinance_news, "yf_retry", lambda fn: fn())


@pytest.fixture()
def real_retry_no_sleep(monkeypatch):
    """Keep yfinance's real ``yf_retry`` but make its backoff instant.

    Covers the "backoff exhausted -> raw YFRateLimitError re-raised" path.
    """
    import tradingagents.dataflows.stockstats_utils as su
    import tradingagents.dataflows.y_finance as y_finance
    import tradingagents.dataflows.yfinance_news as yfinance_news

    monkeypatch.setattr(y_finance, "yf_retry", su.yf_retry)
    monkeypatch.setattr(yfinance_news, "yf_retry", su.yf_retry)
    monkeypatch.setattr(su.time, "sleep", lambda seconds: None)
