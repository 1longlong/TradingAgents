"""Finnhub-only news scope: the experiment's single news provider.

The 16-run CAND-01 x Batch-Macro study is registered as **Finnhub-only**. That
is a statement about the real execution path, not about a config string, so the
tests here drive ``route_to_vendor`` and the analyst-facing tools and intercept
``gdelt_news`` at the module boundary. Anything that imports GDELT lazily would
still be caught, because the interceptor is installed on the *module attribute*
the lazy import resolves to.

Covered:

* the shipped default routes both news tools to Finnhub and nothing else;
* ``get_news_finnhub_only`` never touches GDELT, even when Finnhub fails;
* a Finnhub failure renders as a failure, never as "no news" and never as a
  silent GDELT rescue;
* global news answers ``CONFIG_DISABLED`` (a deliberate absence) rather than
  borrowing Finnhub company news;
* the rendered provenance line names only the providers actually merged.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows import finnhub_news, gdelt_news, interface
from tradingagents.dataflows.news_merge import ProviderOutcome, merge_news_sections
from tradingagents.dataflows.news_status import NewsStatus

START = "2026-09-01"
END = "2026-09-30"


@pytest.fixture
def gdelt_tripwire(monkeypatch):
    """Make any GDELT contact fail loudly and count it."""
    calls = []

    def _trip(provider):
        def _inner(*args, **kwargs):
            calls.append((provider, args, kwargs))
            raise AssertionError(f"GDELT was contacted: {provider}{args}{kwargs}")

        return _inner

    for name, provider in (
        ("get_news_gdelt", "get_news_gdelt"),
        ("get_global_news_gdelt", "get_global_news_gdelt"),
    ):
        monkeypatch.setattr(gdelt_news, name, _trip(provider))
        for method in ("get_news", "get_global_news"):
            if provider in interface.VENDOR_METHODS[method]:
                monkeypatch.setitem(
                    interface.VENDOR_METHODS[method], "gdelt", _trip(provider)
                )
    return calls


@pytest.fixture
def finnhub_down(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated Finnhub outage")

    monkeypatch.setattr(finnhub_news, "get_news_finnhub", _boom)


# --- configuration ----------------------------------------------------------


def test_default_config_has_no_gdelt_news_route():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["tool_vendors"]["get_news"] == "finnhub"
    assert DEFAULT_CONFIG["tool_vendors"]["get_global_news"] == "finnhub"
    assert "gdelt" not in DEFAULT_CONFIG["tool_vendors"]["get_news"]
    assert "gdelt" not in DEFAULT_CONFIG["tool_vendors"]["get_global_news"]


def test_the_finnhub_company_route_is_the_finnhub_only_entry_point():
    assert (
        interface.VENDOR_METHODS["get_news"]["finnhub"]
        is finnhub_news.get_news_finnhub_only
    )
    # The two-provider merge is retained for historical evidence scripts but
    # must not be reachable through the routing table.
    assert (
        finnhub_news.get_news_combined
        not in interface.VENDOR_METHODS["get_news"].values()
    )


# --- real execution path ----------------------------------------------------


def test_get_news_never_contacts_gdelt(gdelt_tripwire, monkeypatch):
    monkeypatch.setattr(
        finnhub_news,
        "get_news_finnhub",
        lambda *a, **k: "### NVDA beats estimates (source: Reuters)\n"
        "**Published:** 2026-09-22T10:00:00+00:00\nLink: https://example.test/1",
    )
    from tradingagents.agents.utils.news_data_tools import get_news

    out = get_news.invoke(
        {"ticker": "NVDA", "start_date": START, "end_date": END}
    )

    assert "NVDA beats estimates" in out
    assert gdelt_tripwire == [], f"GDELT contacted: {gdelt_tripwire}"


def test_a_finnhub_outage_is_not_rescued_by_gdelt(gdelt_tripwire, finnhub_down):
    from tradingagents.agents.utils.news_data_tools import get_news

    out = get_news.invoke(
        {"ticker": "NVDA", "start_date": START, "end_date": END}
    )

    assert gdelt_tripwire == [], f"GDELT contacted: {gdelt_tripwire}"
    assert "DATA_UNAVAILABLE" in out
    # The failure must not read as a confirmed quiet period.
    assert "no verifiable NVDA news" in out
    assert "confirmed absence" in out


def test_global_news_is_explicitly_disabled_not_borrowed(gdelt_tripwire):
    from tradingagents.agents.utils.news_data_tools import get_global_news

    out = get_global_news.invoke({"curr_date": "2026-09-30"})

    assert gdelt_tripwire == [], f"GDELT contacted: {gdelt_tripwire}"
    assert "NEWS_STATUS=CONFIG_DISABLED" in out
    assert "no global/macro endpoint" in out


def test_the_disabled_global_path_fetches_nothing(monkeypatch, gdelt_tripwire):
    """No network call of any kind may back the disabled global path."""
    import urllib.request

    def _no_network(*args, **kwargs):  # pragma: no cover - tripwire
        raise AssertionError(f"network access: {args}")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    out = finnhub_news.get_global_news_finnhub("2026-09-30")
    assert "CONFIG_DISABLED" in out


# --- honest provenance ------------------------------------------------------


def test_single_provider_header_names_only_that_provider(monkeypatch):
    monkeypatch.setattr(
        finnhub_news,
        "get_news_finnhub",
        lambda *a, **k: "### NVDA beats estimates (source: Reuters)\n"
        "**Published:** 2026-09-22T10:00:00+00:00\nLink: https://example.test/1",
    )
    out = finnhub_news.get_news_finnhub_only("NVDA", START, END)

    assert "Finnhub company news" in out
    assert "GDELT" not in out, "a Finnhub-only block must not claim GDELT coverage"


def test_header_lists_both_providers_when_both_are_merged():
    ok = ProviderOutcome(
        provider="Finnhub",
        status=NewsStatus.SUCCESS_REAL_CONTENT,
        text="### NVDA beats estimates (source: Reuters)\n"
        "**Published:** 2026-09-22T10:00:00+00:00\nLink: https://example.test/1",
    )
    other = ProviderOutcome(
        provider="GDELT",
        status=NewsStatus.EMPTY_VALID,
        text="",
    )
    out = merge_news_sections([ok, other], ticker="NVDA",
                              start_date=START, end_date=END)
    assert "Finnhub company news + GDELT discovery" in out


def test_single_provider_failure_says_the_configured_provider():
    failure = ProviderOutcome(
        provider="Finnhub", status=NewsStatus.RATE_LIMITED, text=""
    )
    out = merge_news_sections([failure], ticker="NVDA",
                              start_date=START, end_date=END)
    assert "from the configured provider" in out
    assert "any provider" not in out
