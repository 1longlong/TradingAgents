"""Configurable LLM SDK retry budget (#1090/#1091).

A single transient 429 burst used to kill an otherwise-healthy multi-agent run
because each provider SDK's max_retries (default 2) was not exposed. This adds an
opt-in llm_max_retries knob forwarded to every provider chat client.
"""
from __future__ import annotations

import importlib

import pytest

import tradingagents.default_config as default_config_module
from tradingagents.graph.trading_graph import TradingAgentsGraph, _coerce_max_retries

# --- coercion / validation -------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("value,expected", [(0, 0), (2, 2), (10, 10), ("6", 6)])
def test_coerce_accepts_non_negative_ints_and_numeric_strings(value, expected):
    assert _coerce_max_retries(value) == expected


@pytest.mark.unit
@pytest.mark.parametrize("bad", [-1, "-3"])
def test_coerce_rejects_negative(bad):
    with pytest.raises(ValueError, match=">= 0"):
        _coerce_max_retries(bad)


@pytest.mark.unit
@pytest.mark.parametrize("bad", [True, False])
def test_coerce_rejects_booleans(bad):
    with pytest.raises(ValueError, match="boolean"):
        _coerce_max_retries(bad)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["abc", "1.5", None])
def test_coerce_rejects_non_integers(bad):
    with pytest.raises(ValueError, match="integer"):
        _coerce_max_retries(bad)


# --- forwarding into provider kwargs --------------------------------------

def _bare_graph(config):
    g = object.__new__(TradingAgentsGraph)
    g.config = config
    return g


@pytest.mark.unit
def test_not_forwarded_when_unset():
    kwargs = _bare_graph({"llm_provider": "openai", "llm_max_retries": None})._get_provider_kwargs()
    assert "max_retries" not in kwargs


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
def test_forwarded_across_providers(provider):
    kwargs = _bare_graph({"llm_provider": provider, "llm_max_retries": 6})._get_provider_kwargs()
    assert kwargs["max_retries"] == 6


@pytest.mark.unit
def test_forwarded_env_string_is_coerced():
    # env vars arrive as strings; the consumer coerces (like temperature)
    kwargs = _bare_graph({"llm_provider": "openai", "llm_max_retries": "4"})._get_provider_kwargs()
    assert kwargs["max_retries"] == 4


@pytest.mark.unit
def test_invalid_config_value_fails_loudly():
    with pytest.raises(ValueError):
        _bare_graph({"llm_provider": "openai", "llm_max_retries": -1})._get_provider_kwargs()


# --- env overlay -----------------------------------------------------------

def _reload_with_env(monkeypatch, **overrides):
    for key in list(default_config_module._ENV_OVERRIDES):
        monkeypatch.delenv(key, raising=False)
    for key, val in overrides.items():
        monkeypatch.setenv(key, val)
    return importlib.reload(default_config_module)


@pytest.mark.unit
def test_default_is_none(monkeypatch):
    dc = _reload_with_env(monkeypatch)
    assert dc.DEFAULT_CONFIG["llm_max_retries"] is None


@pytest.mark.unit
def test_env_override_sets_config(monkeypatch):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_LLM_MAX_RETRIES="8")
    # None-default key: env value arrives as a string and is coerced downstream.
    assert dc.DEFAULT_CONFIG["llm_max_retries"] == "8"
    assert _coerce_max_retries(dc.DEFAULT_CONFIG["llm_max_retries"]) == 8


# --- regression: the budget must reach the OpenAI-compatible client -------
# ``openai_compatible`` previously ignored max_retries (kwargs were dropped
# before constructing the SDK client), so a single transient read timeout
# aborted a benchmark run instead of being retried.

@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_retry_budget_reaches_openai_chat_client(monkeypatch, provider):
    from tradingagents.llm_clients.openai_client import OpenAIClient

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    client = OpenAIClient(
        "gpt-4o-mini", base_url="https://example.invalid/v1", provider=provider,
        max_retries=3,
    )
    llm = client.get_llm()
    # LangChain passes max_retries to the underlying SDK client.
    assert llm.root_client.max_retries == 3


# --- regression: only real ChatOpenAI parameters may cross into the SDK -----
# ``llm_kwargs.update(self.kwargs)`` forwarded *every* constructor kwarg to
# ``ChatOpenAI(...)``. An internal config key or a LangChain-only argument then
# raised ``TypeError: unexpected keyword argument`` (or, via ``extra_body``, got
# smuggled into the request body). The handoff is a whitelist; the knobs that
# matter for reliability — ``timeout``, ``max_retries``, temperature, client
# objects — must still pass.

@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_timeout_and_retries_both_reach_chat_client(monkeypatch, provider):
    from tradingagents.llm_clients.openai_client import OpenAIClient

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    client = OpenAIClient(
        "gpt-4o-mini", base_url="https://example.invalid/v1", provider=provider,
        timeout=45, max_retries=3,
    )
    llm = client.get_llm()
    assert llm.root_client.max_retries == 3
    assert llm.request_timeout == 45


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_max_tokens_is_mapped_to_max_completion_tokens(monkeypatch, provider):
    from tradingagents.llm_clients.openai_client import OpenAIClient

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    client = OpenAIClient(
        "gpt-4o-mini", base_url="https://example.invalid/v1", provider=provider,
        max_tokens=1234,
    )
    llm = client.get_llm()
    assert llm.max_tokens == 1234


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_internal_kwargs_are_not_forwarded(monkeypatch, provider):
    """Internal / LangChain-only keys must not reach the SDK chat constructor."""
    from tradingagents.llm_clients.openai_client import OpenAIClient

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    client = OpenAIClient(
        "gpt-4o-mini", base_url="https://example.invalid/v1", provider=provider,
        max_retries=2,
        # Internal graph config that is not a ChatOpenAI parameter.
        llm_provider="openai_compatible",
        max_debate_rounds=2,
        # LangChain-only base-class parameter, not accepted by ChatOpenAI's
        # OpenAI client kwargs.
        verbose_tracing=True,
    )
    llm = client.get_llm()  # must not raise TypeError
    assert llm.root_client.max_retries == 2
    assert llm.max_tokens is None
    for leaked in ("llm_provider", "max_debate_rounds", "verbose_tracing"):
        assert leaked not in (llm.model_kwargs or {})


@pytest.mark.unit
def test_whitelist_covers_every_forwarded_parameter():
    """Every key the registry branch forwards is a real ChatOpenAI parameter."""
    from tradingagents.llm_clients import openai_client as oc

    accepted = {
        "timeout", "max_retries", "temperature", "http_client",
        "http_async_client", "max_completion_tokens",
    }
    assert set(oc._SPEC_CLIENT_KWARGS.values()) <= accepted
    # The user-facing names callers actually pass must all be covered.
    for user_key in ("timeout", "max_retries", "temperature", "max_tokens"):
        assert user_key in oc._SPEC_CLIENT_KWARGS
