"""Regressions from independent audit A (news & data path), half 2.

Audit A confirmed the Finnhub-only routing but found that three things around it
were still unsafe for a paid 16-run study. Each test here fails on the audited
code and passes after the fix, so none of them is a restatement of a property
that already held.

A-01  The child process was never given ``FINNHUB_API_KEY``, so all 16 runs
      would have rendered ``AUTH_MISSING`` while the config claimed a working
      Finnhub news path.
A-02  With no ``trade_date`` (any call outside a graph run) the point-in-time
      cutoff was dropped entirely, so news up to the end of ``end_date`` was
      admitted.
A-03  ``CONFIG_DISABLED`` used the same "could not answer" sentence as a real
      outage, inviting a reader to wait for a recovery that never comes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tradingagents.dataflows.news_status import NewsStatus, render_status

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --- A-01: the study's only news credential reaches the child --------------


def test_finnhub_api_key_is_forwarded_to_the_child():
    """The 16-run harness must carry the news vendor's credential."""
    import scripts.token_benchmark as harness

    assert "FINNHUB_API_KEY" in harness._PASSTHROUGH_ENV


def test_finnhub_api_key_is_reported_in_credential_state():
    """A missing news key must be visible before the round starts, not after."""
    import scripts.token_benchmark as harness

    state = {row["variable"]: row["configured"]
             for row in harness.credential_state({"FINNHUB_API_KEY": "x"})}
    assert state["FINNHUB_API_KEY"] is True

    unset = {row["variable"]: row["configured"]
             for row in harness.credential_state({})}
    assert unset["FINNHUB_API_KEY"] is False


def test_apply_cityu_env_installs_the_finnhub_key(tmp_path, monkeypatch):
    """End-to-end: a secrets file's news key really lands in the child env."""
    import scripts.token_benchmark as harness

    secrets = tmp_path / "secrets.env"
    secrets.write_text("FINNHUB_API_KEY=from-secrets-file\n")

    env = {k: v for k, v in os.environ.items() if k != "FINNHUB_API_KEY"}
    # Second positional parameter is ``secrets_path``; passing it by keyword
    # would need the harness's parameter name, which is not part of its contract.
    harness.apply_cityu_env(env, secrets)
    assert env["FINNHUB_API_KEY"] == "from-secrets-file"


# --- A-02: the point-in-time cutoff cannot be silently dropped --------------


def _capture_route(monkeypatch):
    calls = []

    def _route(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return "route-result"

    # ``route_to_vendor`` is imported *into* this module, so the name the tool
    # actually calls is ``news_data_tools.route_to_vendor``.
    from tradingagents.agents.utils import news_data_tools

    monkeypatch.setattr(news_data_tools, "route_to_vendor", _route)
    return calls


def test_get_news_with_a_trade_date_uses_it_as_the_cutoff(monkeypatch):
    from tradingagents.agents.utils import news_data_tools

    calls = _capture_route(monkeypatch)
    news_data_tools.get_news.func("NVDA", "2026-09-01", "2026-09-23", "2026-09-21")

    assert calls, "route_to_vendor was never called"
    cutoff = calls[0][2].get("as_of_cutoff")
    assert cutoff is not None, "the PIT cutoff was dropped"
    assert "2026-09-22" in str(cutoff), cutoff


def test_get_news_without_a_trade_date_still_applies_a_cutoff(monkeypatch):
    """The audited bug: no trade_date used to mean no cutoff at all."""
    from tradingagents.agents.utils import news_data_tools

    calls = _capture_route(monkeypatch)
    news_data_tools.get_news.func("NVDA", "2026-09-01", "2026-09-23", "")

    assert calls, "route_to_vendor was never called"
    cutoff = calls[0][2].get("as_of_cutoff")
    assert cutoff is not None, (
        "dropping the cutoff when trade_date is empty admits post-decision news"
    )
    # The window's own end date is the latest defensible boundary.
    assert "2026-09-24" in str(cutoff), cutoff


def test_the_cutoff_is_strictly_after_the_window_end(monkeypatch):
    """A cutoff at or before end_date would discard the window's own last day."""
    from tradingagents.agents.utils import news_data_tools

    calls = _capture_route(monkeypatch)
    news_data_tools.get_news.func("NVDA", "2026-09-01", "2026-09-23", "")

    cutoff = calls[0][2]["as_of_cutoff"]
    text = str(cutoff)
    assert text[:10] >= "2026-09-24", f"cutoff {text} truncates the window"


# --- A-03: a deliberate exclusion must not read as an outage --------------


def test_config_disabled_is_not_described_as_an_outage():
    text = render_status(
        NewsStatus.CONFIG_DISABLED,
        vendor="Finnhub",
        subject="global market",
        start_date="2026-09-30",
        end_date="2026-09-30",
        detail="no global endpoint",
    )
    assert "NEWS_STATUS=CONFIG_DISABLED" in text
    assert "could not answer" not in text, (
        "an exclusion that reads as an outage invites waiting for recovery"
    )
    assert "no error occurred" in text
    assert "excluded" in text


@pytest.mark.parametrize(
    "status",
    [
        NewsStatus.AUTH_MISSING,
        NewsStatus.AUTH_INVALID,
        NewsStatus.RATE_LIMITED,
        NewsStatus.TIMEOUT,
        NewsStatus.PROVIDER_UNAVAILABLE,
        NewsStatus.HTTP_ERROR,
        NewsStatus.PARSE_ERROR,
    ],
)
def test_real_failures_still_say_the_vendor_could_not_answer(status):
    """The fix must not soften genuine failures."""
    text = render_status(
        status, vendor="Finnhub", subject="NVDA",
        start_date="2026-09-01", end_date="2026-09-30",
    )
    assert "could not answer" in text
    assert "no error occurred" not in text


def test_disabled_global_news_uses_the_new_wording_end_to_end():
    from tradingagents.dataflows.finnhub_news import get_global_news_finnhub

    out = get_global_news_finnhub("2026-09-30")
    assert "CONFIG_DISABLED" in out
    assert "no error occurred" in out
