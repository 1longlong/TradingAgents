"""Finnhub company-news adapter: transport, parsing, PIT, relevance, rendering.

Mocked tests: the transport is replaced with a canned HTTP answer, so these pin
the adapter's own logic without touching the network or a real credential.

Covers the failure surface the task calls out explicitly — 401/403, 429,
timeouts, 5xx, invalid JSON, empty bodies — plus PIT boundaries, timezone
conversion, dedupe, and the relevance rule that a ``related`` match alone is
*not* evidence of company relevance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tradingagents.dataflows.finnhub_news as fn
from tradingagents.dataflows.errors import (
    VendorNotConfiguredError,
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
)
from tradingagents.dataflows.news_status import NewsStatus

START, END = "2026-09-16", "2026-09-23"
CUTOFF = "2026-09-23T20:00:00Z"

#: ``tests/conftest.py`` replaces ``_request`` with a stub so no test can dial
#: out. The credential tests below need the *real* transport wrapper (they pin
#: its redaction path), so they call this captured original, not the attribute.
_REAL_REQUEST = fn._request.__wrapped__ if hasattr(fn._request, "__wrapped__") else fn._request


def _epoch(text: str) -> int:
    return int(
        datetime.strptime(text, "%Y-%m-%d %H:%M")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _item(headline, when, *, summary="", url=None, related="NVDA", source="Reuters"):
    return {
        "category": "company",
        "datetime": _epoch(when),
        "headline": headline,
        "id": 1,
        "related": related,
        "source": source,
        "summary": summary,
        "url": url or f"https://example.invalid/{abs(hash(headline)) % 999983}",
    }


def _call(items, *, status=200, body=None, error_kind="", cutoff=CUTOFF, limit=None):
    """Run ``fetch_news_finnhub`` against a canned transport answer."""
    payload = body if body is not None else json.dumps(items)
    with patch.object(fn, "_request", return_value=(status, payload, error_kind)), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 50}), \
            patch.object(fn.time, "sleep"):
        return fn.fetch_news_finnhub(
            "NVDA", START, END, as_of_cutoff=cutoff, limit=limit
        )


# --- 1. normal response ----------------------------------------------------


def test_normal_response_maps_every_documented_field():
    item = _item(
        "Nvidia beats quarterly estimates",
        "2026-09-20 13:00",
        summary="Data-center revenue rose.",
        url="https://reuters.invalid/nvidia-beats",
        related="NVDA,AMD",
        source="Reuters",
    )
    outcome = _call([item])

    assert outcome.status is None
    assert len(outcome.articles) == 1
    article = outcome.articles[0]
    # The unified shape the rest of the pipeline reads.
    assert article["ticker"] == "NVDA"
    assert article["headline"] == "Nvidia beats quarterly estimates"
    assert article["summary"] == "Data-center revenue rose."
    assert article["source"] == "Reuters"
    assert article["url"] == "https://reuters.invalid/nvidia-beats"
    assert article["provider"] == "finnhub"
    assert article["related"] == ["NVDA", "AMD"]
    assert article["published_at"] == datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc)
    assert article["status"] is NewsStatus.SUCCESS_REAL_CONTENT


# --- 2. HTTP 401 / 403 ------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_auth_rejection_is_typed_unavailable_not_an_empty_day(status):
    with pytest.raises(VendorUnavailableError):
        _call([], status=status, body="")
    assert fn._classify_http(status, "") is NewsStatus.AUTH_INVALID


# --- 3. HTTP 429 ------------------------------------------------------------


def test_rate_limit_retries_once_then_raises_the_throttle_type():
    with pytest.raises(VendorRateLimitError):
        _call([], status=429, body="")
    # Bounded: the adapter must not spin.
    with patch.object(fn, "_request", return_value=(429, "", "")) as request, \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 5}), \
            patch.object(fn.time, "sleep"):
        with pytest.raises(VendorRateLimitError):
            fn.fetch_news_finnhub("NVDA", START, END)
    assert request.call_count == fn._MAX_ATTEMPTS


# --- 4. timeout -------------------------------------------------------------


def test_timeout_is_its_own_type_and_is_not_a_throttle():
    with pytest.raises(VendorTimeoutError) as ctx:
        _call([], status=None, body=None, error_kind="timeout")
    assert not isinstance(ctx.value, VendorRateLimitError)


# --- 5. 5xx -----------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_errors_are_typed_unavailable(status):
    with pytest.raises(VendorUnavailableError):
        _call([], status=status, body="")


# --- 6. empty result --------------------------------------------------------


def test_an_authoritative_empty_list_is_a_real_absence():
    outcome = _call([])
    assert outcome.status is NewsStatus.EMPTY_VALID
    assert outcome.articles == []


def test_an_empty_body_is_a_real_absence_not_a_crash():
    outcome = _call([], body="")
    assert outcome.status is NewsStatus.EMPTY_VALID


# --- 7. invalid JSON --------------------------------------------------------


def test_invalid_json_is_a_parse_error_not_an_empty_day():
    outcome = _call([], body="<html>bad gateway</html>")
    assert outcome.status is NewsStatus.PARSE_ERROR


def test_a_json_object_instead_of_a_list_is_a_parse_error():
    outcome = _call([], body=json.dumps({"unexpected": "shape"}))
    assert outcome.status is NewsStatus.PARSE_ERROR


def test_an_in_band_error_object_raises_rather_than_reading_as_no_news():
    # Finnhub answers some plan/auth problems with HTTP 200 + {"error": ...}.
    with pytest.raises(VendorUnavailableError):
        _call([], body=json.dumps({"error": "You don't have access to this resource."}))


# --- 8. duplicates ----------------------------------------------------------


def test_duplicate_urls_collapse_to_one_article():
    outcome = _call([
        _item("Nvidia raises guidance", "2026-09-21 10:00", url="https://a.invalid/1"),
        _item("Nvidia raises guidance", "2026-09-21 10:00", url="https://a.invalid/1"),
    ])
    assert len(outcome.articles) == 1


# --- 9. wrong-ticker relevance ---------------------------------------------


def test_related_alone_does_not_qualify_an_unrelated_sector_piece():
    # The measured failure mode: a sector round-up carries related="NVDA".
    outcome = _call([
        _item("Semiconductor sector outlook improves", "2026-09-21 10:00",
              summary="Chip demand is rising across the industry.", related="NVDA"),
    ])
    assert outcome.articles == []
    assert outcome.status is NewsStatus.EMPTY_VALID


def test_another_companys_story_is_not_admitted():
    outcome = _call([
        _item("Advanced Micro Devices wins a data-center contract",
              "2026-09-21 10:00", related="NVDA"),
    ])
    assert outcome.articles == []


# --- 10. correct alias matching --------------------------------------------


@pytest.mark.parametrize("headline", [
    "Nvidia beats quarterly estimates",
    "NVIDIA Corporation announces a buyback",
    "NVDA climbs after the data-center update",
    "Analysts lift Nvidia price target",
])
def test_genuinely_company_articles_are_admitted(headline):
    outcome = _call([_item(headline, "2026-09-21 10:00")])
    assert len(outcome.articles) == 1, headline


def test_a_lowercase_url_slug_qualifies_the_article():
    # News URLs are overwhelmingly lowercase; a case-sensitive symbol match
    # would silently drop these.
    outcome = _call([
        _item("Chipmaker rallies on demand", "2026-09-21 10:00",
              url="https://site.invalid/2026/09/nvda-rallies-on-demand"),
    ])
    assert len(outcome.articles) == 1


# --- 15. after the trade date ----------------------------------------------


def test_an_article_after_the_cutoff_is_rejected():
    outcome = _call([_item("Nvidia after-hours scoop", "2026-09-23 21:00")])
    assert outcome.articles == []


def test_a_future_dated_article_is_never_admitted():
    outcome = _call([_item("Nvidia tomorrow", "2026-09-25 09:00")])
    assert outcome.articles == []


# --- 16. exact boundary -----------------------------------------------------


def test_the_cutoff_instant_itself_is_excluded():
    # Half-open [start, cutoff): an article stamped exactly at the cutoff is out.
    at_cutoff = _item("Nvidia at cutoff", "2026-09-23 20:00")
    outcome = _call([at_cutoff])
    assert outcome.articles == []


def test_the_last_instant_before_the_cutoff_is_included():
    just_before = _item("Nvidia just before cutoff", "2026-09-23 19:59")
    outcome = _call([just_before])
    assert len(outcome.articles) == 1


# --- 17. timezone conversion ------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    (1790173800, "2026-09-23T14:30:00+00:00"),
    (1790173800000, "2026-09-23T14:30:00+00:00"),  # milliseconds
    ("1790173800", "2026-09-23T14:30:00+00:00"),   # numeric string
])
def test_epoch_shapes_all_normalise_to_utc(raw, expected):
    assert fn._parse_published(raw).isoformat() == expected


@pytest.mark.parametrize("raw", [None, "", "garbage", 0, -1, True, {}, []])
def test_unusable_timestamps_are_rejected_not_guessed(raw):
    assert fn._parse_published(raw) is None


def test_an_undated_article_is_dropped_and_never_rendered():
    item = _item("Nvidia undated", "2026-09-21 10:00")
    item["datetime"] = None
    outcome = _call([item])
    assert outcome.articles == []


# --- cross-trade-date contamination ----------------------------------------


def test_a_previous_days_article_does_not_leak_into_a_later_window():
    # An article published the day before the window must not appear.
    outcome = _call([_item("Nvidia before window", "2026-09-15 23:59")])
    assert outcome.articles == []


def test_a_later_cutoff_admits_what_an_earlier_one_rejected():
    # The PIT rule is applied per call, so the same payload answers differently
    # for different trade dates rather than being cached across them.
    item = _item("Nvidia evening story", "2026-09-23 22:00")
    early = _call([item], cutoff=CUTOFF)
    late = _call([item], cutoff="2026-09-24T00:00:00Z")
    assert early.articles == []
    assert len(late.articles) == 1


# --- credential handling ----------------------------------------------------


def test_a_missing_credential_is_not_configured_not_an_empty_day():
    with patch.object(fn, "_request", return_value=(200, "[]", "")), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 5}), \
            patch.dict("os.environ", {"FINNHUB_API_KEY": ""}):
        with pytest.raises(VendorNotConfiguredError):
            fn.fetch_news_finnhub("NVDA", START, END)


def test_the_credential_never_reaches_a_log_line_or_exception():
    leak = "sk-live-should-never-appear"

    def _raise(*_a, **_k):
        # Simulate a transport that echoes the full URL in its message.
        raise OSError(f"failed GET https://finnhub.io/api/v1/company-news?token={leak}")

    with patch("urllib.request.urlopen", side_effect=_raise), \
            patch.object(fn.logger, "warning") as warn:
        status, _body, kind = _REAL_REQUEST(f"https://finnhub.io/x?token={leak}")
    assert status is None and kind == "transport"
    assert warn.called, "a transport failure must be logged"
    logged = " ".join(str(c) for c in warn.call_args_list)
    assert leak not in logged
    assert "<redacted>" in logged


def test_redaction_masks_every_credential_parameter():
    for param in ("token", "apikey", "api_key", "access_token", "key", "secret", "password"):
        raw = f"https://host.invalid/p?{param}=abc123XYZ&other=keep"
        redacted = fn._redact(raw)
        assert "abc123XYZ" not in redacted, param
        assert "other=keep" in redacted, param


# --- window chunking: Finnhub's 250-record cap truncates the OLDEST end ------
#
# Measured live (2026-11-15, NVDA, from=2026-09-16&to=2026-09-24): one call
# returned 247 records ALL published on/after 2026-09-23T16:45, i.e. zero
# articles before the cutoff, although NVDA publishes ~100-180 items a day.
# Shrinking the range recovered 707 in-window articles. A single wide call
# therefore must not be trusted to represent its whole window.


def _call_per_day(by_date, *, cutoff=CUTOFF):
    """Answer each per-day sub-request with that day's canned records.

    ``by_date`` maps ``"YYYY-MM-DD"`` to a list of items. Any day not present
    answers with an empty list, exactly as Finnhub does for a quiet day.
    """
    seen_queries = []

    def _fake_request(url, *_args, **_kwargs):
        # The URL carries the token; only the date range is inspected.
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(url).query)
        day = params["from"][0]
        seen_queries.append((params["from"][0], params["to"][0]))
        return 200, json.dumps(by_date.get(day, [])), ""

    with patch.object(fn, "_request", side_effect=_fake_request), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 50}), \
            patch.object(fn.time, "sleep"):
        outcome = fn.fetch_news_finnhub("NVDA", START, END, as_of_cutoff=cutoff)
    return outcome, seen_queries


def test_the_window_is_split_into_per_day_requests():
    # One HTTP call per requested day, so the 250 cap can never swallow a day.
    _, queries = _call_per_day({})
    assert queries == [
        ("2026-09-16", "2026-09-16"),
        ("2026-09-17", "2026-09-17"),
        ("2026-09-18", "2026-09-18"),
        ("2026-09-19", "2026-09-19"),
        ("2026-09-20", "2026-09-20"),
        ("2026-09-21", "2026-09-21"),
        ("2026-09-22", "2026-09-22"),
        ("2026-09-23", "2026-09-23"),
    ]


def test_articles_from_early_days_survive_the_split():
    # The wide-call truncation dropped everything before 09-23; per-day fetching
    # keeps the earlier days that a truncated response would have hidden.
    outcome, _ = _call_per_day({
        "2026-09-17": [_item("Nvidia unveils new GPU architecture", "2026-09-17 14:00")],
        "2026-09-22": [_item("Nvidia wins large data center contract", "2026-09-22 09:00")],
    })
    assert outcome.status is None
    headlines = {a["headline"] for a in outcome.articles}
    assert headlines == {
        "Nvidia unveils new GPU architecture",
        "Nvidia wins large data center contract",
    }


def test_a_truncated_day_is_recorded_rather_than_hidden(caplog):
    # A day that returns exactly the server cap is truncated at its oldest end;
    # the caller must be told, never left believing the day was fully covered.
    full_day = [
        _item(f"Nvidia story {i}", "2026-09-22 12:00", url=f"https://x.invalid/{i}")
        for i in range(fn._MAX_RECORDS_PER_CALL)
    ]
    with caplog.at_level("WARNING"):
        outcome, _ = _call_per_day({"2026-09-22": full_day})
    assert outcome.status is None
    assert any("record cap" in r.message for r in caplog.records)


def test_an_empty_every_day_window_is_a_real_absence():
    outcome, _ = _call_per_day({})
    assert outcome.status is NewsStatus.EMPTY_VALID


def test_a_failure_on_one_day_chunk_raises_rather_than_reporting_partial():
    # Partial coverage must never be presented as a complete window.
    from tradingagents.dataflows.errors import VendorUnavailableError

    calls = {"n": 0}

    def _fake_request(url, *_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            return 503, "", ""
        return 200, json.dumps([]), ""

    with patch.object(fn, "_request", side_effect=_fake_request), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 50}), \
            patch.object(fn.time, "sleep"):
        with pytest.raises(VendorUnavailableError):
            fn.fetch_news_finnhub("NVDA", START, END, as_of_cutoff=CUTOFF)


def test_chunk_count_is_bounded_for_a_very_wide_range():
    # A caller asking for years must not turn into hundreds of requests.
    chunks = fn._day_chunks(
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert len(chunks) <= fn._MAX_CHUNKS
    assert chunks[-1][1] == "2026-01-01"
    # Ranges tile the window without gaps.
    for (_, prev_to), (next_from, _) in zip(chunks, chunks[1:]):
        assert prev_to < next_from


def test_truncation_reaches_the_analyst_facing_text():
    # Logging the truncation is not enough: the analyst reads the rendered
    # block, so the coverage note must appear there (audit finding, 2026-11-15).
    full_day = [
        _item(f"Nvidia story {i}", "2026-09-22 12:00", url=f"https://x.invalid/{i}")
        for i in range(fn._MAX_RECORDS_PER_CALL)
    ]

    def _fake_request(url, *_args, **_kwargs):
        from urllib.parse import parse_qs, urlparse

        day = parse_qs(urlparse(url).query)["from"][0]
        body = full_day if day == "2026-09-22" else []
        return 200, json.dumps(body), ""

    with patch.object(fn, "_request", side_effect=_fake_request), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 500}), \
            patch.object(fn.time, "sleep"):
        text = fn.get_news_finnhub("NVDA", "2026-09-21", "2026-09-22",
                                   as_of_cutoff=CUTOFF)

    assert "Coverage note" in text
    assert "record cap" in text


# ---------------------------------------------------------------------------
# Truncation must keep the newest articles, not the oldest
# ---------------------------------------------------------------------------
def _items(n_days: list[tuple[str, int]]) -> dict[str, list[dict]]:
    """``[(date, count)]`` -> per-day canned Finnhub payloads, oldest first."""
    by_date: dict[str, list[dict]] = {}
    for day, count in n_days:
        by_date[day] = [
            {
                "headline": f"NVDA item {i} on {day}",
                "summary": "NVIDIA news",
                "url": f"https://example.test/{day}/{i}",
                # Spread the day's items across it: 30 items must not walk past
                # hour 23, and each timestamp must stay inside the window.
                "datetime": _epoch(f"{day} {i // 2:02d}:{(i % 2) * 30:02d}"),
                "related": "NVDA",
            }
            for i in range(count)
        ]
    return by_date


def test_article_limit_keeps_the_newest_articles():
    """Regression: ``admitted[:limit]`` kept the *oldest* articles.

    Finnhub returns records oldest-first, so slicing off the tail discarded the
    days immediately before the trade date -- exactly the coverage a dated
    decision depends on. Live evidence before the fix: NVDA 2026-09-23 saw
    20 articles whose newest was 2026-09-16, while 63 in-window articles from
    the final two days were dropped.
    """
    by_date = _items([("2026-09-16", 30), ("2026-09-21", 30), ("2026-09-22", 30)])
    with patch.object(fn, "_request") as request, \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 10}), \
            patch.object(fn.time, "sleep"):
        from urllib.parse import parse_qs, urlparse

        def _fake(url, *_a, **_k):
            day = parse_qs(urlparse(url).query)["from"][0]
            return 200, json.dumps(by_date.get(day, [])), ""

        request.side_effect = _fake
        outcome = fn.fetch_news_finnhub("NVDA", START, END, as_of_cutoff=CUTOFF)

    kept = outcome.articles
    assert len(kept) == 10
    # The kept set is the ten newest, i.e. the whole of the final day.
    assert all(a["published_at"].date().isoformat() == "2026-09-22" for a in kept)
    # And it is chronological, so rendering does not have to reorder.
    stamps = [a["published_at"] for a in kept]
    assert stamps == sorted(stamps)
    # Nothing from the oldest day survives.
    assert not any(a["published_at"].date().isoformat() == "2026-09-16"
                   for a in kept)


def test_article_limit_still_respects_the_pit_cutoff():
    """Keeping the newest must never reach past the point-in-time cutoff."""
    by_date = _items([("2026-09-22", 5)])
    with patch.object(fn, "_request") as request, \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config", return_value={"news_article_limit": 50}), \
            patch.object(fn.time, "sleep"):
        from urllib.parse import parse_qs, urlparse

        def _fake(url, *_a, **_k):
            day = parse_qs(urlparse(url).query)["from"][0]
            return 200, json.dumps(by_date.get(day, [])), ""

        request.side_effect = _fake
        outcome = fn.fetch_news_finnhub("NVDA", START, END, as_of_cutoff=CUTOFF)

    cutoff_dt = datetime(2026, 9, 23, 20, 0, tzinfo=timezone.utc)
    for article in outcome.articles:
        assert article["published_at"] < cutoff_dt
