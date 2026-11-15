"""Dual-source integration: Finnhub company news + GDELT global/industry news.

The two providers are *not* interchangeable feeds and must not be concatenated as
though they were. These tests pin the properties that make the combined block
safe to hand to the News Analyst:

* a failing provider never erases a working one's real articles (the CAND-01
  failure mode, where one source's outage blanked the whole node);
* one provider failing does not make the node ``UNAVAILABLE``;
* both failing produces an honest reason, not "no news";
* a genuine empty answer from both is an absence, not an outage;
* ``AVAILABLE`` records that real articles arrived, never a sentiment.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tradingagents.dataflows.finnhub_news as fn
import tradingagents.dataflows.gdelt_news as gn
from tradingagents.dataflows.errors import (
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
)
from tradingagents.dataflows.news_merge import (
    ProviderOutcome,
    combine_status,
    merge_news_sections,
)
from tradingagents.dataflows.news_status import NewsStatus

START, END = "2026-09-16", "2026-09-23"


def _epoch(text: str) -> int:
    return int(
        datetime.strptime(text, "%Y-%m-%d %H:%M")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _fh_item(headline, when, *, url=None, related="NVDA"):
    return {
        "category": "company",
        "datetime": _epoch(when),
        "headline": headline,
        "id": 1,
        "related": related,
        "source": "Reuters",
        "summary": "",
        "url": url or f"https://example.invalid/{abs(hash(headline)) % 999983}",
    }


def _combined(*, finnhub=None, gdelt=None):
    """Call ``get_news_combined`` with mocked adapters.

    ``finnhub`` is either a list of items, a callable raising an exception, or a
    ``(status, body)`` pair for a transport-level answer.
    """
    def _fh(*_a, **_k):
        if callable(finnhub):
            return finnhub()
        return finnhub if finnhub is not None else ""

    def _gd(*_a, **_k):
        if callable(gdelt):
            return gdelt()
        return gdelt if gdelt is not None else ""

    with patch.object(fn, "get_news_finnhub", side_effect=_fh), \
            patch.object(gn, "get_news_gdelt", side_effect=_gd):
        return fn.get_news_combined("NVDA", START, END)


# --- 1. both succeed --------------------------------------------------------


def test_both_providers_contribute_a_labelled_section():
    fh = (
        "## NVDA News, from 2026-09-16 to 2026-09-23\n\n"
        "### Nvidia beats estimates (source: Reuters)\n"
        "**Published:** 2026-09-20T13:00:00+00:00\n"
        "Link: https://example.invalid/1\n"
    )
    gd = (
        "## NVDA global/industry news\n\n"
        "### Chip demand rises (source: site.invalid)\n"
        "Link: https://site.invalid/2\n"
    )
    out = _combined(finnhub=lambda: fh, gdelt=lambda: gd)

    assert "Finnhub" in out
    assert "GDELT" in out
    assert "Nvidia beats estimates" in out
    assert "Chip demand rises" in out
    assert out.startswith("## NVDA News")
    # The provider sections use ``####`` so they are never counted as articles.
    assert "#### Finnhub" in out and "#### GDELT" in out
    # ``### `` is the article-line marker downstream consumers count; no provider
    # header may ever be counted as an article.
    article_lines = [ln for ln in out.splitlines() if ln.startswith("### ")]
    assert len(article_lines) == 2, article_lines  # the two fixture articles only


# --- 2. one provider fails, the other has real news -------------------------


def test_a_finnhub_timeout_does_not_erase_gdelt_articles():
    gd = (
        "## NVDA global/industry news\n\n"
        "### Chip demand rises (source: site.invalid)\n"
        "Link: https://site.invalid/2\n"
    )

    def _boom():
        raise VendorTimeoutError("Finnhub timed out")

    out = _combined(finnhub=_boom, gdelt=lambda: gd)

    assert "Chip demand rises" in out
    # The outage is still visible, and the overall status is not a failure.
    assert "TIMEOUT" in out
    assert "Overall status: SUCCESS_REAL_CONTENT" in out
    assert "DATA_UNAVAILABLE" not in out


def test_a_gdelt_rate_limit_does_not_erase_finnhub_articles():
    fh = (
        "## NVDA News, from 2026-09-16 to 2026-09-23\n\n"
        "### Nvidia beats estimates (source: Reuters)\n"
        "Link: https://example.invalid/1\n"
    )

    def _boom():
        raise VendorRateLimitError("GDELT rate limited")

    out = _combined(finnhub=lambda: fh, gdelt=_boom)

    assert "Nvidia beats estimates" in out
    assert "RATE_LIMITED" in out
    assert "Overall status: SUCCESS_REAL_CONTENT" in out


# --- 3. both fail -----------------------------------------------------------


def test_both_providers_failing_is_an_honest_unavailable_with_both_reasons():
    def _finnhub():
        raise VendorUnavailableError("Finnhub 503")

    def _gdelt():
        raise VendorTimeoutError("GDELT timed out")

    out = _combined(finnhub=_finnhub, gdelt=_gdelt)

    assert "DATA_UNAVAILABLE" in out
    assert "Finnhub" in out and "GDELT" in out
    # Never presented as an absence of news.
    assert "no news" not in out.lower() or "not an absence of news" in out.lower()


# --- 4. both genuinely empty ------------------------------------------------


def test_both_providers_genuinely_empty_is_a_real_absence_not_an_outage():
    out = _combined(
        finnhub=lambda: "NEWS_STATUS=EMPTY_VALID: Finnhub answered and had no articles",
        gdelt=lambda: "NEWS_STATUS=EMPTY_VALID: GDELT answered and had no articles",
    )
    assert "EMPTY_VALID" in out
    assert "DATA_UNAVAILABLE" not in out


# --- 5. CAND-01 regression --------------------------------------------------


def test_the_cand01_failure_mode_is_closed():
    """One provider's outage must not blank the node.

    In the CAND-01 batch macro run, the sole news vendor failed and the analyst
    received a bare outage string; combined with the other research inputs this
    read as "no negative news". Now: real GDELT articles survive a Finnhub
    outage, and the outage is labelled beside them.
    """
    gd = (
        "## NVDA global/industry news\n\n"
        "### Nvidia supplier warns on margins (source: wire.invalid)\n"
        "**Published:** 2026-09-22T09:00:00+00:00\n"
        "Link: https://wire.invalid/3\n"
    )

    def _finnhub_out():
        raise VendorUnavailableError("Finnhub endpoint not serving")

    out = _combined(finnhub=_finnhub_out, gdelt=lambda: gd)

    # The negative article is delivered, not swallowed.
    assert "supplier warns on margins" in out
    assert "Overall status: SUCCESS_REAL_CONTENT" in out
    assert "DATA_UNAVAILABLE" not in out


# --- 6. status semantics ----------------------------------------------------


def test_available_means_articles_arrived_not_a_view():
    outcome = ProviderOutcome(
        "Finnhub",
        "### Something (source: Reuters)\n**Published:** 2026-09-20T13:00:00+00:00",
    )
    assert outcome.proves_real_news
    assert outcome.status is NewsStatus.SUCCESS_REAL_CONTENT
    # The merged header must not imply direction.
    text = merge_news_sections([outcome], ticker="NVDA",
                               start_date=START, end_date=END)
    lowered = text.lower()
    for word in ("bullish", "bearish", "positive", "negative sentiment"):
        assert word not in lowered


def test_combine_status_does_not_hide_a_failure_behind_an_empty_answer():
    # Only when *every* provider answered "nothing" is the overall status a
    # genuine absence. One provider saying nothing says nothing about the
    # coverage the other provider failed to deliver, so the failure wins.
    empty = ProviderOutcome("GDELT", "NEWS_STATUS=EMPTY_VALID: nothing")
    failed = ProviderOutcome("Finnhub", "NEWS_STATUS=TIMEOUT: down")
    assert combine_status([failed, empty]) is NewsStatus.TIMEOUT
    assert combine_status([empty, empty]) is NewsStatus.EMPTY_VALID


def test_unknown_is_not_treated_as_neutral():
    # An unparsable answer is not EMPTY_VALID and not SUCCESS.
    outcome = ProviderOutcome("Finnhub", "NEWS_STATUS=PARSE_ERROR: junk")
    assert outcome.status is NewsStatus.PARSE_ERROR
    assert not outcome.proves_real_news


# --- 7. PIT is carried through the merge ------------------------------------


def test_a_future_article_is_rejected_by_the_provider_not_the_merger():
    # The merger must not invent timestamps or re-admit what the provider
    # dropped: a Finnhub window with only a post-cutoff item yields no article.
    payload = [_fh_item("Nvidia after-hours scoop", "2026-09-23 21:00")]
    body = json.dumps(payload)

    with patch.object(fn, "_request", return_value=(200, body, "")), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 20}):
        outcome = fn.fetch_news_finnhub(
            "NVDA", START, END, as_of_cutoff="2026-09-23T20:00:00Z"
        )

    assert outcome.articles == []
    assert outcome.status is NewsStatus.OUT_OF_WINDOW


# --- 8. routing --------------------------------------------------------------


def test_the_registered_providers_are_finnhub_and_gdelt_only():
    from tradingagents.dataflows.interface import VENDOR_METHODS

    assert list(VENDOR_METHODS["get_news"]) == ["finnhub", "gdelt"]
    # Finnhub has no global endpoint: it is registered so the Finnhub-only scope
    # can answer CONFIG_DISABLED explicitly instead of borrowing another feed.
    assert list(VENDOR_METHODS["get_global_news"]) == ["finnhub", "gdelt"]


def test_the_configured_news_scope_is_finnhub_only():
    """The shipped default must not route company *or* global news to GDELT."""
    from tradingagents.default_config import DEFAULT_CONFIG

    tool_vendors = DEFAULT_CONFIG["tool_vendors"]
    assert tool_vendors["get_news"] == "finnhub"
    assert tool_vendors["get_global_news"] == "finnhub"


# --- cross-provider duplicates are one piece of evidence --------------------
#
# Audit finding (2026-11-15): the same story served by both feeds used to be
# rendered twice, double-counting coverage and inflating the evidence.


def _article(title: str, url: str, source: str = "Reuters") -> str:
    return (
        f"### {title} (source: {source})\n"
        f"**Published:** 2026-09-22T10:00:00+00:00\n"
        f"Link: {url}"
    )


def _outcome(provider: str, articles: list[str]) -> ProviderOutcome:
    text = f"{len(articles)} article(s):\n\n" + "\n\n".join(articles)
    return ProviderOutcome(provider, text)


def test_the_same_url_from_both_providers_is_rendered_once():
    finnhub = _outcome("Finnhub", [
        _article("Nvidia beats on data-center revenue", "https://example.com/a"),
        _article("Nvidia unveils Rubin rack", "https://example.com/b"),
    ])
    gdelt = _outcome("GDELT", [
        _article("Nvidia beats on data-center revenue", "https://example.com/a"),
    ])
    out = merge_news_sections([finnhub, gdelt], ticker="NVDA",
                              start_date="2026-09-16", end_date="2026-09-23")
    assert out.count("example.com/a") == 1
    assert sum(1 for line in out.splitlines() if line.startswith("### ")) == 2
    assert "duplicate" in out.lower()


def test_url_variants_of_the_same_story_also_collapse():
    # Vendors differ on scheme, `www.`, trailing slash and tracking parameters.
    finnhub = _outcome("Finnhub", [
        _article("Nvidia beats on data-center revenue", "https://example.com/a"),
    ])
    gdelt = _outcome("GDELT", [
        _article("Nvidia beats on data-center revenue",
                 "http://www.example.com/a/?utm_source=gdelt", "reuters.com"),
    ])
    out = merge_news_sections([finnhub, gdelt], ticker="NVDA",
                              start_date="2026-09-16", end_date="2026-09-23")
    assert sum(1 for line in out.splitlines() if line.startswith("### ")) == 1


def test_distinct_articles_from_both_providers_are_both_kept():
    finnhub = _outcome("Finnhub", [
        _article("Nvidia beats on data-center revenue", "https://example.com/a"),
    ])
    gdelt = _outcome("GDELT", [
        _article("Nvidia supplier lifts capex", "https://elsewhere.invalid/z"),
    ])
    out = merge_news_sections([finnhub, gdelt], ticker="NVDA",
                              start_date="2026-09-16", end_date="2026-09-23")
    assert sum(1 for line in out.splitlines() if line.startswith("### ")) == 2


# --- regressions from the 2026-11-15 live run ------------------------------
#
# Three defects appeared only against the real vendors, because all three live
# in rendering/query construction *after* the HTTP layer returns. They are
# pinned here so they cannot come back silently.


def _finnhub_style(i: int) -> str:
    # Finnhub serves articles as /api/news?id=<hash>: the identity lives in the
    # query string, which a naive canonicaliser strips.
    return f"https://finnhub.io/api/news?id={i:064x}"


def test_all_of_one_providers_articles_survive_when_the_other_fails():
    # Live defect: GDELT was rate-limited, so it contributed nothing, yet the
    # merge reported "19 duplicate article(s) also served by another provider"
    # and kept 1 of 20 articles.
    articles = [_article(f"Nvidia story {i}", _finnhub_style(i)) for i in range(20)]
    finnhub = _outcome("Finnhub", articles)
    gdelt = ProviderOutcome(
        "GDELT", "NEWS_STATUS=RATE_LIMITED: throttled", NewsStatus.RATE_LIMITED
    )
    out = merge_news_sections([finnhub, gdelt], ticker="NVDA",
                              start_date="2026-09-17", end_date="2026-09-23")
    assert sum(1 for line in out.splitlines() if line.startswith("### ")) == 20
    assert "duplicate" not in out


def test_identity_bearing_query_parameters_are_not_stripped_from_the_key():
    from tradingagents.dataflows.news_merge import _url_key

    a = _url_key("https://finnhub.io/api/news?id=aaa")
    b = _url_key("https://finnhub.io/api/news?id=bbb")
    assert a != b
    # Tracking parameters are still ignored, so the same story still matches.
    assert _url_key("https://example.com/a?utm_source=x") == _url_key("https://example.com/a")


def test_a_providers_own_document_header_is_not_nested_in_the_merged_block():
    # Live defect: the merged block contained a second "## NVDA News, from …"
    # heading inside the Finnhub section.
    inner = (
        "## NVDA News, from 2026-09-17 to 2026-09-23 "
        "(Finnhub company news, publish time verified per article):\n\n"
        "1 article(s) published inside the window:\n\n"
        + _article("Nvidia beats", "https://example.com/a")
    )
    out = merge_news_sections([ProviderOutcome("Finnhub", inner)], ticker="NVDA",
                              start_date="2026-09-17", end_date="2026-09-23")
    assert out.count("## NVDA News, from") == 1
    assert "1 article(s) published inside the window" in out
