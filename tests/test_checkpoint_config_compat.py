"""Checkpoint compatibility with the run's execution settings.

A checkpoint may only be resumed by a run that would execute the same work.
These tests pin that rule end to end, on a **real** ``SqliteSaver`` checkpoint
and the real ``TradingAgentsGraph`` lifecycle (``begin_checkpoint`` /
``checkpoint_input``), not just on signature strings:

* identical settings resume, and a finished node is not executed twice;
* defaults and explicit same values are one identity (resume);
* a tool allowance, news input, model or language change starts a NEW thread
  (and the allowance that applies is the new one);
* an output-directory change still resumes the original thread;
* a previous run's checkpoint stays on disk when a new one starts;
* credentials and URLs never reach the identity, the signature or the log.

Everything is offline: a scripted model, a tiny counting graph, no vendor.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import tempfile
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpointer import (
    checkpoint_step,
    get_checkpointer,
    thread_id,
)
from tradingagents.graph.market_governance import parse_market_tool_governance
from tradingagents.graph.run_identity import (
    IDENTITY_VERSION,
    execution_digest,
    execution_identity,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph

TICKER = "AAPL"
DATE = "2026-08-14"


# ---------------------------------------------------------------------------
# A counting graph driven through the real checkpoint lifecycle
# ---------------------------------------------------------------------------


class _State(TypedDict, total=False):
    executed: list


class _Counter:
    """Runs are scripted per node; a ``crash_at`` node raises instead."""

    def __init__(self, crash_at=None):
        self.crash_at = crash_at
        self.ran = []

    def node(self, name):
        def run(state):
            self.ran.append(name)
            if self.crash_at == name:
                raise RuntimeError(f"{name} crashed")
            return {"executed": [*(state.get("executed") or []), name]}

        return run


def _workflow(counter, names=("analyst", "trader")):
    wf = StateGraph(_State)
    for name in names:
        wf.add_node(name, counter.node(name))
    wf.add_edge(START, names[0])
    for a, b in zip(names, names[1:], strict=False):
        wf.add_edge(a, b)
    wf.add_edge(names[-1], END)
    return wf


class _Graph(TradingAgentsGraph):
    """``TradingAgentsGraph`` with only the real checkpoint lifecycle wired."""

    def __init__(self, config, counter, names=("analyst", "trader")):
        self.config = config
        self.selected_analysts = ("market",)
        self.workflow = _workflow(counter, names)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None
        self._resuming = False


def _config(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["checkpoint_enabled"] = True
    cfg["data_cache_dir"] = tempfile.mkdtemp()
    cfg["results_dir"] = tempfile.mkdtemp()
    cfg.update(overrides)
    return cfg


class _Invocation:
    """What one CLI-style invocation did: its thread, output and decision."""

    def __init__(self, thread, out, resuming):
        self.thread = thread
        self.out = out
        self.resuming = resuming


def _run(config, counter, *, names=("analyst", "trader")):
    """One full CLI-style invocation: begin -> stream -> end.

    ``end_checkpoint`` clears ``_resuming`` (the graph is back to planning the
    next run), so the decision is captured while it is still live.
    """
    graph = _Graph(config, counter, names)
    tid = graph.begin_checkpoint(TICKER, DATE, "stock")
    payload = graph.checkpoint_input({"executed": []})
    resuming = graph._resuming
    gcfg = {"configurable": {"thread_id": tid}}
    try:
        if payload is None:
            out = graph.graph.invoke(None, gcfg)
        else:
            out = graph.graph.invoke(payload, gcfg)
    finally:
        graph.end_checkpoint()
    return _Invocation(tid, out, resuming)


def _first_run_then_crash(config):
    """Run the analyst, crash at the trader; return the checkpointed config."""
    counter = _Counter(crash_at="trader")
    with pytest.raises(RuntimeError, match="trader crashed"):
        _run(config, counter)
    assert counter.ran == ["analyst", "trader"]
    return counter


# ---------------------------------------------------------------------------
# The identity function itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_identity_is_deterministic_and_versioned():
    cfg = _config()
    assert execution_identity(cfg) == execution_identity(copy.deepcopy(cfg))
    assert execution_identity(cfg)["version"] == IDENTITY_VERSION
    assert execution_digest(cfg) == execution_digest(copy.deepcopy(cfg))
    assert len(execution_digest(cfg)) == 16


@pytest.mark.unit
def test_identity_reads_only_the_passed_mapping(monkeypatch):
    """No global configuration is read or switched."""
    import tradingagents.dataflows.config as live

    calls = []
    monkeypatch.setattr(live, "get_config", lambda: calls.append(1) or {})
    monkeypatch.setattr(live, "set_config", lambda cfg: calls.append(2))
    execution_identity(_config())
    assert calls == [], "the identity must not touch the global config"


@pytest.mark.unit
def test_defaults_equal_explicit_same_values():
    implicit = _config(market_tool_governance={"enabled": True})
    explicit = _config(
        market_tool_governance={"enabled": True, "max_rounds": 4, "max_calls": 10}
    )
    assert execution_identity(implicit) == execution_identity(explicit)
    assert execution_digest(implicit) == execution_digest(explicit)

    # A partially explicit section fills the rest from the defaults.
    partial = _config(market_tool_governance={"enabled": True, "max_rounds": 4})
    assert execution_digest(partial) == execution_digest(implicit)


@pytest.mark.unit
def test_disabled_section_ignores_its_inert_caps():
    """A disabled analyst's caps are never read, so they cannot change a run."""
    base = _config()
    odd = _config(
        market_tool_governance={"enabled": False, "max_rounds": 9, "max_calls": 3},
        news_tool_governance={"enabled": False, "max_rounds": 1, "max_calls": 1},
    )
    assert execution_identity(base) == execution_identity(odd)
    # And an enabled section's caps do count.
    enabled = _config(market_tool_governance={"enabled": True, "max_rounds": 9, "max_calls": 3})
    assert execution_identity(enabled) != execution_identity(base)


@pytest.mark.unit
def test_vendor_chain_order_is_significant():
    a = _config(data_vendors={**DEFAULT_CONFIG["data_vendors"],
                              "news_data": "yfinance,alpha_vantage"})
    b = _config(data_vendors={**DEFAULT_CONFIG["data_vendors"],
                              "news_data": "alpha_vantage,yfinance"})
    assert execution_digest(a) != execution_digest(b)
    assert execution_identity(a)["vendor_chains"]["get_news"] == "yfinance,alpha_vantage"


@pytest.mark.unit
def test_tool_level_vendor_overrides_the_category():
    cfg = _config(data_vendors={**DEFAULT_CONFIG["data_vendors"], "news_data": "yfinance"},
                  tool_vendors={"get_news": "alpha_vantage"})
    ident = execution_identity(cfg)
    assert ident["vendor_chains"]["get_news"] == "alpha_vantage"
    assert ident["vendor_chains"]["get_global_news"] == "yfinance"


@pytest.mark.unit
def test_execution_changes_are_visible_and_display_changes_are_not():
    base = execution_digest(_config())
    changed = {
        "max_calls 10->1": ("market_tool_governance",
                            {"enabled": True, "max_rounds": 4, "max_calls": 1}),
        "news_article_limit": ("news_article_limit", 5),
        "global_news_article_limit": ("global_news_article_limit", 3),
        "global_news_lookback_days": ("global_news_lookback_days", 30),
        "global_news_queries": ("global_news_queries", ["only this one"]),
        "news vendor": ("data_vendors",
                        {**DEFAULT_CONFIG["data_vendors"], "news_data": "alpha_vantage"}),
        "provider": ("llm_provider", "anthropic"),
        "quick model": ("quick_think_llm", "another-model"),
        "deep model": ("deep_think_llm", "another-deep-model"),
        "temperature": ("temperature", 0.1),
        "max_tokens": ("max_tokens", 4096),
        "language": ("output_language", "Chinese"),
    }
    for label, (key, value) in changed.items():
        assert execution_digest(_config(**{key: value})) != base, label

    unchanged = {
        "results_dir": tempfile.mkdtemp(),
    }
    assert execution_digest(_config(results_dir=unchanged["results_dir"])) == base
    assert execution_digest(_config(debug=True)) == base
    assert execution_digest(_config(output_language="english")) == base
    assert execution_digest(_config(some_display_flag=True)) == base


@pytest.mark.unit
@pytest.mark.parametrize("provider,key", [
    ("openai", "openai_reasoning_effort"),
    ("google", "google_thinking_level"),
    ("anthropic", "anthropic_effort"),
])
def test_provider_effort_counts_only_for_the_provider_that_reads_it(provider, key):
    base = execution_digest(_config(llm_provider=provider))
    assert execution_digest(_config(llm_provider=provider, **{key: "high"})) != base
    # A key the selected provider does not forward is inert.
    other = {"openai": "google_thinking_level", "google": "anthropic_effort",
             "anthropic": "openai_reasoning_effort"}[provider]
    assert execution_digest(_config(llm_provider=provider, **{other: "high"})) == base


@pytest.mark.unit
def test_credentials_and_urls_never_reach_identity_signature_or_log(caplog):
    secret_url = "https://user:sk-live-SECRET@example.invalid/v1"
    cfg = _config(backend_url=secret_url, llm_provider="openai_compatible")
    cfg["api_key"] = "sk-should-not-appear"

    ident = json.dumps(execution_identity(cfg))
    graph = object.__new__(TradingAgentsGraph)
    graph.config = cfg
    graph.selected_analysts = ("market",)
    signature = graph._run_signature("stock")

    for blob in (ident, signature):
        assert "SECRET" not in blob
        assert "sk-" not in blob
        assert "backend_url" not in blob
        assert "example.invalid" not in blob

    with caplog.at_level(logging.INFO):
        counter = _Counter(crash_at="trader")
        with pytest.raises(RuntimeError):
            _run(cfg, counter)
        _run(cfg, _Counter())
    text = caplog.text
    assert secret_url not in text
    assert "SECRET" not in text and "sk-" not in text
    assert "Starting fresh" in text


# ---------------------------------------------------------------------------
# Real checkpoint lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_identical_settings_resume_without_repeating_finished_nodes():
    cfg = _config()
    _first_run_then_crash(cfg)

    resumed = _Counter()
    run = _run(cfg, resumed)
    assert run.resuming is True
    assert resumed.ran == ["trader"], "the analyst must not run a second time"
    assert run.out["executed"] == ["analyst", "trader"]


@pytest.mark.integration
def test_default_and_explicit_same_values_resume_the_same_thread():
    implicit = _config(market_tool_governance={"enabled": True})
    # Crash first, then resume with the explicit form of the same settings.
    with pytest.raises(RuntimeError):
        _run(implicit, _Counter(crash_at="trader"))

    explicit = {**implicit,
                "market_tool_governance": {"enabled": True, "max_rounds": 4, "max_calls": 10}}
    resumed = _Counter()
    run = _run(explicit, resumed)
    assert run.resuming is True
    assert resumed.ran == ["trader"]


@pytest.mark.integration
def test_tool_allowance_change_starts_a_new_thread_with_the_new_allowance():
    old = _config(market_tool_governance={"enabled": True, "max_rounds": 4, "max_calls": 10})
    with pytest.raises(RuntimeError):
        _run(old, _Counter(crash_at="trader"))
    old_sig = _Graph(old, _Counter())._run_signature("stock")

    new = {**old, "market_tool_governance": {"enabled": True, "max_rounds": 4, "max_calls": 1}}
    counter = _Counter()
    run = _run(new, counter)
    assert run.resuming is False, "a changed allowance must not resume"
    assert counter.ran == ["analyst", "trader"], "a new run executes from the start"
    assert parse_market_tool_governance(new).max_calls == 1

    # The old checkpoint is still there, under its own thread id.
    assert checkpoint_step(new["data_cache_dir"], TICKER, DATE, old_sig) is not None

    # And the new run's own state carries the NEW config (not the old one).
    with get_checkpointer(new["data_cache_dir"], TICKER) as saver:
        saved = saver.get_tuple({"configurable": {"thread_id": run.thread}})
    assert saved.checkpoint["channel_values"]["executed"] == ["analyst", "trader"]


@pytest.mark.integration
@pytest.mark.parametrize("label,overrides", [
    ("news_article_limit", {"news_article_limit": 5}),
    ("global_news_article_limit", {"global_news_article_limit": 3}),
    ("news vendor", {"data_vendors": {**DEFAULT_CONFIG["data_vendors"],
                                      "news_data": "alpha_vantage"}}),
    ("quick model", {"quick_think_llm": "another-model"}),
    ("provider", {"llm_provider": "anthropic"}),
    ("language", {"output_language": "Chinese"}),
])
def test_execution_changes_start_a_new_thread(label, overrides):
    base = _config()
    with pytest.raises(RuntimeError):
        _run(base, _Counter(crash_at="trader"))

    counter = _Counter()
    run = _run({**base, **overrides}, counter)
    assert run.resuming is False, label
    assert counter.ran == ["analyst", "trader"], label


@pytest.mark.integration
def test_results_dir_change_resumes_the_original_thread():
    base = _config()
    with pytest.raises(RuntimeError):
        _run(base, _Counter(crash_at="trader"))

    counter = _Counter()
    run = _run({**base, "results_dir": tempfile.mkdtemp()}, counter)
    assert run.resuming is True
    assert counter.ran == ["trader"]


@pytest.mark.integration
def test_old_checkpoint_survives_a_new_run():
    cfg = _config()
    with pytest.raises(RuntimeError):
        _run(cfg, _Counter(crash_at="trader"))
    graph = _Graph(cfg, _Counter())
    old_sig = graph._run_signature("stock")
    old_tid = thread_id(TICKER, DATE, old_sig)
    assert checkpoint_step(cfg["data_cache_dir"], TICKER, DATE, old_sig) is not None

    new = {**cfg, "llm_provider": "anthropic"}
    run = _run(new, _Counter())
    assert run.resuming is False
    assert run.thread != old_tid

    # The database and the old thread are untouched by the new run.
    assert checkpoint_step(cfg["data_cache_dir"], TICKER, DATE, old_sig) is not None
    with get_checkpointer(cfg["data_cache_dir"], TICKER) as saver:
        assert saver.get_tuple({"configurable": {"thread_id": old_tid}}) is not None
        assert saver.get_tuple({"configurable": {"thread_id": run.thread}}) is not None


@pytest.mark.integration
def test_a_legacy_signature_checkpoint_is_never_resumed():
    """A checkpoint whose thread id predates the identity is not compatible."""
    cfg = _config()
    legacy_signature = "|".join([
        "analysts=market", "debate=1", "risk=1", "asset=stock",
        "market_gov=False", "fundamentals_gov=False", "news_gov=False",
        "sentiment_prefetch=False", "portfolio=none",
    ])
    legacy_tid = thread_id(TICKER, DATE, legacy_signature)
    # Write a real checkpoint under the pre-identity thread id, the way an
    # older release left it on disk: same ticker+date, no version, no digest.
    from langgraph.checkpoint.base import empty_checkpoint

    legacy_checkpoint = empty_checkpoint()
    legacy_checkpoint["channel_values"] = {"executed": ["analyst", "trader"]}
    with get_checkpointer(cfg["data_cache_dir"], TICKER) as saver:
        saver.put(
            {"configurable": {"thread_id": legacy_tid, "checkpoint_ns": ""}},
            legacy_checkpoint,
            {"step": 2, "source": "loop", "parents": {}},
            {},
        )
    assert checkpoint_step(cfg["data_cache_dir"], TICKER, DATE, legacy_signature) is not None

    counter = _Counter()
    run = _run(cfg, counter)
    assert run.thread != legacy_tid
    assert run.resuming is False
    assert counter.ran == ["analyst", "trader"]
    # ...and the old checkpoint is still readable, untouched.
    assert checkpoint_step(cfg["data_cache_dir"], TICKER, DATE, legacy_signature) is not None


@pytest.mark.integration
def test_signature_keeps_the_graph_shape_isolation():
    graph = object.__new__(TradingAgentsGraph)
    graph.config = _config()
    graph.selected_analysts = ("market",)
    base = graph._run_signature("stock")
    assert base.startswith(f"run_version={IDENTITY_VERSION}|")
    assert f"|exec={execution_digest(graph.config)}" in base
    assert graph._run_signature("crypto") != base
    graph.selected_analysts = ("market", "news")
    assert graph._run_signature("stock") != base


@pytest.mark.unit
def test_digest_is_stable_across_runs():
    """The same settings from two fresh constructions produce one digest."""
    a = execution_digest(_config())
    b = execution_digest(_config())
    assert a == b
    assert a == hashlib.sha256(
        json.dumps(execution_identity(_config()), sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()[:16]
