"""GDELT DOC API adapter: parsing, failure classes, PIT, and macro queries.

GDELT needs no credential, so the only thing between it and the analyst is this
adapter's classification. The properties pinned here:

* a failed query is never reported as "no news";
* 429, timeouts, empty answers and malformed JSON are told apart;
* publisher timestamps are verified, and nothing at or after the cutoff is kept;
* company queries are relevance-filtered, macro queries are not;
* a window older than GDELT's archive is refused instead of answered "nothing".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import tradingagents.dataflows.gdelt_news as gn
from tradingagents.dataflows.errors import (
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
)
from tradingagents.dataflows.news_status import NewsStatus

#: ``tests/conftest.py`` stubs the transport wrappers. These two tests pin the
#: wrappers' own redaction, so they call the captured originals.
_REAL_REQUEST = gn._request.__wrapped__ if hasattr(gn._request, "__wrapped__") else gn._request
_REAL_FETCH_PAGE = (
    gn._fetch_page.__wrapped__ if hasattr(gn._fetch_page, "__wrapped__") else gn._fetch_page
)


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _recent_window(days: int = 5):
    """A window inside GDELT's ~3-month archive."""
    end = _today() - timedelta(days=2)
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


START, END = _recent_window()


def _doc_response(titles):
    return json.dumps({"articles": [
        {"title": t, "url": f"https://site.invalid/{i}", "domain": "site.invalid",
         "seendate": "20260920T120000Z"}
        for i, t in enumerate(titles)
    ]})


def _call_gdelt(*, body, status=200, error_kind="", pages=None, start=None, end=None):
    """Run ``get_news_gdelt`` with a canned DOC answer and page fetches."""
    start = start or START
    end = end or END
    page_map = pages or {}

    def _fake_page(url):
        return page_map.get(url, (404, "", ""))

    with patch.object(gn, "_request", return_value=(status, body, error_kind)), \
            patch.object(gn, "_fetch_page", side_effect=_fake_page), \
            patch.object(gn, "_throttle", lambda: None), \
            patch.object(gn, "get_config",
                         return_value={"news_verify_budget": 8}):
        return gn.get_news_gdelt("NVDA", start, end)


def _page_with_time(iso: str) -> str:
    return (
        '<html><head><script type="application/ld+json">'
        f'{{"datePublished": "{iso}"}}'
        "</script></head><body>x</body></html>"
    )


def _in_window_iso() -> str:
    """A publication time three days ago, inside :func:`_recent_window`."""
    return (_today() - timedelta(days=3)).strftime("%Y-%m-%dT12:00:00+00:00")


# --- 1. normal response -----------------------------------------------------


def test_normal_response_keeps_verified_company_articles():
    when = (_today() - timedelta(days=3)).strftime("%Y-%m-%dT12:00:00+00:00")
    body = _doc_response(["Nvidia beats quarterly estimates"])
    pages = {"https://site.invalid/0": (200, _page_with_time(when), "")}

    out = _call_gdelt(body=body, pages=pages)

    assert "Nvidia beats quarterly estimates" in out
    assert "https://site.invalid/0" in out
    assert when[:10] in out


# --- 2. HTTP 429 ------------------------------------------------------------


def test_rate_limit_is_its_own_type_after_a_bounded_retry():
    with patch.object(gn, "_request", return_value=(429, "", "")) as request, \
            patch.object(gn, "_throttle", lambda: None), \
            patch.object(gn.time, "sleep") as sleep, \
            patch.object(gn, "get_config", return_value={"news_verify_budget": 8}):
        with pytest.raises(VendorRateLimitError):
            gn.get_news_gdelt("NVDA", START, END)
    # Bounded: exactly one retry, never more.
    assert request.call_count == gn._MAX_ATTEMPTS
    # The retry waits the measured backoff, not the documented 5 s interval:
    # GDELT sends no Retry-After and was measured to still 429 after 5.5 s.
    sleep.assert_called_once_with(gn._RATE_LIMIT_BACKOFF_SECONDS)
    assert gn._RATE_LIMIT_BACKOFF_SECONDS > 5.5


# --- 3. timeout -------------------------------------------------------------


def test_a_timeout_is_not_reported_as_no_news():
    with pytest.raises(VendorTimeoutError):
        _call_gdelt(body=None, status=None, error_kind="timeout")


# --- 4. empty result --------------------------------------------------------


def test_an_authoritative_empty_answer_is_a_real_absence():
    # GDELT omits "articles" entirely when nothing matched.
    out = _call_gdelt(body=json.dumps({"query": "x"}))
    assert out.startswith("NEWS_STATUS=EMPTY_VALID"), out
    assert "DATA_UNAVAILABLE" not in out


def test_an_empty_body_is_a_real_absence():
    out = _call_gdelt(body="")
    assert "NEWS_STATUS=EMPTY_VALID" in out


# --- 5. malformed JSON ------------------------------------------------------


def test_malformed_json_is_a_parse_error_not_an_absence():
    # A request-level failure is raised (not returned as text) so the router can
    # fail over; the *class* in the message distinguishes a bad body from a
    # genuine "nothing matched".
    with pytest.raises(VendorUnavailableError) as ctx:
        _call_gdelt(body="<html>502</html>")
    assert "parse_error" in str(ctx.value).lower()


def test_a_vendor_query_error_is_an_http_error_not_a_parse_error():
    with pytest.raises(VendorUnavailableError) as ctx:
        _call_gdelt(body="Invalid query end date.")
    assert "http_error" in str(ctx.value).lower()
    assert "parse_error" not in str(ctx.value).lower()


# --- 6. invalid timestamps --------------------------------------------------


def test_articles_without_a_verifiable_publish_time_are_dropped():
    body = _doc_response(["Nvidia story with no timestamp", "Nvidia story with a time"])
    # The first page is unreachable so its time cannot be verified; the second
    # carries a readable date inside the window. Only the verified one may be
    # reported. (When *every* candidate page is unreadable the adapter raises
    # instead — see the taxonomy test for that path.)
    pages = {
        "https://site.invalid/1": (200, _page_with_time(_in_window_iso()), ""),
    }
    out = _call_gdelt(body=body, pages=pages)
    assert "no timestamp" not in out.lower()
    assert "with a time" in out


def test_an_unparsable_publisher_date_is_dropped():
    body = _doc_response(["Nvidia story with a broken date"])
    pages = {"https://site.invalid/0": (200, _page_with_time("not-a-date"), "")}
    out = _call_gdelt(body=body, pages=pages)
    assert "broken date" not in out


# --- 7. PIT -----------------------------------------------------------------


def test_an_article_published_after_the_cutoff_is_rejected():
    future = (_today() + timedelta(days=1)).strftime("%Y-%m-%dT12:00:00+00:00")
    body = _doc_response(["Nvidia future story"])
    pages = {"https://site.invalid/0": (200, _page_with_time(future), "")}
    out = _call_gdelt(body=body, pages=pages)
    assert "future story" not in out


def test_an_article_before_the_window_start_is_rejected():
    old = (_today() - timedelta(days=60)).strftime("%Y-%m-%dT12:00:00+00:00")
    body = _doc_response(["Nvidia stale story"])
    pages = {"https://site.invalid/0": (200, _page_with_time(old), "")}
    out = _call_gdelt(body=body, pages=pages)
    assert "stale story" not in out


def test_a_window_older_than_the_archive_is_refused_not_answered_nothing():
    # No request is made: GDELT cannot reach this far back, so "no news" would
    # be a false statement.
    with patch.object(gn, "_request") as request:
        out = gn.get_news_gdelt("NVDA", "2020-01-01", "2020-01-10")
    assert "NEWS_STATUS=HISTORICAL_UNSUPPORTED" in out
    request.assert_not_called()


# --- 8. relevance -----------------------------------------------------------


def test_a_sector_only_hit_is_not_company_news():
    when = (_today() - timedelta(days=3)).strftime("%Y-%m-%dT12:00:00+00:00")
    body = _doc_response(["Semiconductor industry outlook improves"])
    pages = {"https://site.invalid/0": (200, _page_with_time(when), "")}
    out = _call_gdelt(body=body, pages=pages)
    assert "industry outlook improves" not in out


def test_the_company_name_in_the_title_is_enough():
    when = (_today() - timedelta(days=3)).strftime("%Y-%m-%dT12:00:00+00:00")
    body = _doc_response(["Nvidia unveils a new accelerator"])
    pages = {"https://site.invalid/0": (200, _page_with_time(when), "")}
    out = _call_gdelt(body=body, pages=pages)
    assert "Nvidia unveils a new accelerator" in out


# --- macro queries ----------------------------------------------------------


def test_a_macro_query_names_the_company_but_does_not_require_it():
    # Global news is about the macro topic; requiring the company name would
    # discard every valid item. The company is a corroborating term, not a
    # filter on the results.
    assert gn._global_query("Federal Reserve interest rates", "NVDA").endswith(
        'sourcelang:english'
    )
    assert '"NVIDIA"' in gn._global_query("Federal Reserve interest rates", "NVDA")
    assert "NVDA" not in gn._global_query("Federal Reserve interest rates", None)


def test_a_macro_query_with_nothing_matched_is_a_real_absence():
    start, end = _recent_window(3)
    with patch.object(gn, "_request", return_value=(200, json.dumps({}), "")), \
            patch.object(gn, "_throttle", lambda: None), \
            patch.object(gn, "get_config", return_value={
                "global_news_lookback_days": 3,
                "global_news_article_limit": 5,
                "global_news_queries": ["Federal Reserve interest rates"],
            }):
        out = gn.get_global_news_gdelt(end)
    assert "NEWS_STATUS=EMPTY_VALID" in out


# --- credential hygiene -----------------------------------------------------


def test_a_transport_error_message_is_redacted_before_logging():
    leak = "FAKELEAK123"

    def _raise(*_a, **_k):
        raise OSError(f"reset while fetching https://api.invalid/doc?token={leak}")

    with patch("urllib.request.urlopen", side_effect=_raise), \
            patch.object(gn.logger, "warning") as warn:
        status, _body, kind = _REAL_REQUEST("https://api.invalid/doc?token=" + leak)
    assert status is None and kind == "transport"
    assert warn.called
    logged = " ".join(str(c) for c in warn.call_args_list)
    assert leak not in logged
    assert "<redacted>" in logged


def test_a_publisher_url_with_a_credential_is_redacted_before_logging():
    # GDELT returns arbitrary publisher URLs; one may carry a query credential.
    leak = "FAKELEAK456"
    url = f"https://publisher.invalid/story?token={leak}"

    def _raise(*_a, **_k):
        raise OSError("connection reset")

    with patch("urllib.request.urlopen", side_effect=_raise), \
            patch.object(gn.logger, "warning") as warn:
        _REAL_FETCH_PAGE(url)
    assert warn.called
    logged = " ".join(str(c) for c in warn.call_args_list)
    assert leak not in logged
    assert "<redacted>" in logged


# --- the global path honours a verification budget --------------------------
#
# The company path bounds publisher re-fetches with ``news_verify_budget``; the
# global path previously had no ceiling, so N macro queries x ``limit`` hits
# meant an unbounded number of page fetches per call (audit finding,
# 2026-11-15).


def test_global_news_caps_publisher_page_fetches():
    import tradingagents.dataflows.gdelt_news as gn

    hits = [
        {"title": f"Macro story {i}", "url": f"https://example.invalid/m{i}",
         "domain": "example.invalid", "seendate": "20260922T120000Z"}
        for i in range(50)
    ]
    when = (_today() - timedelta(days=3)).strftime("%Y-%m-%dT12:00:00Z")
    page = f'<html><meta property="article:published_time" content="{when}"></html>'
    fetches = {"n": 0}

    def _fake_page(_url):
        fetches["n"] += 1
        return 200, page, ""

    queries = ["global economic news", "federal reserve rates", "oil energy geopolitics"]
    with patch.object(gn, "_fetch_articles", return_value=(hits, None, "")), \
            patch.object(gn, "_fetch_page", side_effect=_fake_page), \
            patch.object(gn, "_throttle"), \
            patch.object(gn, "get_config", return_value={
                "global_news_lookback_days": 7,
                "global_news_article_limit": 50,
                "global_news_queries": queries,
                "news_verify_budget": 6,
            }):
        out = gn.get_global_news_gdelt(END, look_back_days=7, limit=50)

    # At most the budget, regardless of how many hits the queries returned.
    assert fetches["n"] <= 6, fetches["n"]
    assert "Macro story" in out


def test_global_news_budget_of_zero_does_not_claim_a_real_absence():
    # With no verification performed, hits were still discovered: the honest
    # answer is a coverage gap, not "no macro news exists".
    import tradingagents.dataflows.gdelt_news as gn

    hits = [{"title": "Macro story", "url": "https://example.invalid/m",
             "domain": "example.invalid"}]
    with patch.object(gn, "_fetch_articles", return_value=(hits, None, "")), \
            patch.object(gn, "_throttle"), \
            patch.object(gn, "get_config", return_value={
                "global_news_lookback_days": 7,
                "global_news_article_limit": 10,
                "global_news_queries": ["global economic news"],
                "news_verify_budget": 0,
            }):
        out = gn.get_global_news_gdelt(END, look_back_days=7)

    assert "NEWS_STATUS=" in out
    assert NewsStatus.EMPTY_VALID.value not in out


# --- GDELT boolean grammar: parentheses only around OR ----------------------
#
# Live defect (2026-11-15): every default macro query was wrapped in "(...)"
# although none contained OR, so GDELT rejected all of them with
# "Parentheses may only be used around OR'd statements." and the global path
# raised a mislabelled PARSE_ERROR.


def test_a_plain_and_phrase_is_not_wrapped_in_parentheses():
    import tradingagents.dataflows.gdelt_news as gn

    built = gn._global_query("Federal Reserve interest rates inflation", None)
    assert built == "Federal Reserve interest rates inflation sourcelang:english"


def test_an_explicit_or_phrase_is_parenthesised():
    import tradingagents.dataflows.gdelt_news as gn

    built = gn._global_query("oil OR crude prices", None)
    assert built.startswith("(oil OR crude prices)")
    assert built.endswith("sourcelang:english")


def test_a_ticker_scoped_macro_query_requires_the_company_name():
    import tradingagents.dataflows.gdelt_news as gn
    from tradingagents.dataflows.news_relevance import company_name

    built = gn._global_query("oil commodities energy", "XOM")
    # The scoping term is the company's registered alias, quoted so GDELT
    # requires it as a phrase rather than as loose terms.
    assert f'"{company_name("XOM")}"' in built
    assert built.startswith("oil commodities energy")
    assert "(" not in built


def test_every_default_macro_query_builds_a_parenthesis_free_string():
    from tradingagents.default_config import DEFAULT_CONFIG

    import tradingagents.dataflows.gdelt_news as gn

    for query in DEFAULT_CONFIG["global_news_queries"]:
        built = gn._global_query(query, None)
        assert built, query
        assert "(" not in built, (query, built)


def test_the_parentheses_rejection_is_a_query_error_not_a_parse_error():
    import tradingagents.dataflows.gdelt_news as gn

    body = "Parentheses may only be used around OR'd statements."
    with patch.object(gn, "_throttle"), \
            patch.object(gn, "_request", return_value=(200, body, "")):
        records, status, detail = gn._fetch_articles(
            "oil energy",
            datetime(2026, 9, 17, tzinfo=timezone.utc),
            datetime(2026, 9, 23, tzinfo=timezone.utc),
            10,
        )
    assert records == []
    assert status is NewsStatus.HTTP_ERROR, (status, detail)
    assert "Parentheses" in detail


# --- request pacing and budget ---------------------------------------------
#
# Measured 2026-11-15: 8 of 9 requests at 5.5 s spacing were throttled, while
# isolated requests 20 s apart were accepted 3 times out of 3. The pacing
# constants are therefore part of the contract, not incidental tuning.

#: Captured at import time, *before* the autouse fixture replaces it with a stub.
_REAL_THROTTLE = gn._throttle


def test_the_inter_request_spacing_is_at_least_the_measured_safe_gap():
    # Measured 2026-11-15, one request per gap with no retries in between:
    # 30 s and 45 s were rejected with 429, while 60 s and 90 s were accepted.
    # The shipped spacing must therefore be at least the smallest accepted gap,
    # and the 429 backoff must not be shorter than the spacing it is replacing.
    assert gn._MIN_INTERVAL_SECONDS >= 60.0
    assert gn._RATE_LIMIT_BACKOFF_SECONDS >= gn._MIN_INTERVAL_SECONDS


def test_the_throttle_actually_sleeps_when_calls_are_too_close():
    # The suite-wide fixture patches ``_throttle`` itself to a no-op, so the
    # *original* function is exercised here and its clock/sleep are faked.
    # ``_throttle`` reads monotonic once for "now" and once to record the new
    # timestamp: the first call has nothing to wait for, the second starts
    # immediately after and must wait roughly the whole interval.
    throttle = _REAL_THROTTLE
    gn._reset_throttle_state()
    ticks = iter([1000.0, 1000.0, 1000.1, 1060.1])
    with patch.object(gn.time, "sleep") as sleep, \
            patch.object(gn.time, "monotonic", side_effect=lambda: next(ticks)):
        throttle()
        sleep.assert_not_called()          # first request: no wait
        throttle()
    sleep.assert_called_once()
    assert sleep.call_args.args[0] == pytest.approx(gn._MIN_INTERVAL_SECONDS - 0.1)


def test_the_global_path_never_exceeds_its_request_budget():
    # Five configured queries normally mean five requests; a long list must not
    # multiply into an unbounded burst.
    queries = [f"macro topic {i}" for i in range(40)]
    calls = {"n": 0}

    def _count_articles(*_a, **_k):
        calls["n"] += 1
        return [], NewsStatus.EMPTY_VALID, ""

    with patch.object(gn, "_fetch_articles", side_effect=_count_articles), \
            patch.object(gn, "_throttle"), \
            patch.object(gn, "get_config", return_value={
                "global_news_lookback_days": 7,
                "global_news_article_limit": 10,
                "global_news_queries": queries,
                "news_verify_budget": 8,
                "news_max_requests_per_call": 5,
            }):
        gn.get_global_news_gdelt(END, look_back_days=7)

    assert calls["n"] <= 5, calls["n"]
