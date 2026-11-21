"""Company-news adapter: PIT cutoff, dedupe, and honest failure classes.

These contracts were originally pinned against the Alpha Vantage
``NEWS_SENTIMENT`` adapter, which was the project's only vendor able to serve an
arbitrary historical window. That path was removed in the Finnhub + GDELT
migration; Finnhub's ``company-news`` endpoint is now the symbol-specific
vendor and accepts the same date range, so the same properties are pinned
against it:

* an article published after the decision cutoff is excluded;
* duplicate rows for one headline collapse to one;
* "the vendor returned no articles" is a different string from "the vendor
  could not be asked", so an outage never reads as an absence of news.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tradingagents.dataflows.finnhub_news as fn
from tradingagents.dataflows.date_window import parse_publication_time
from tradingagents.dataflows.errors import (
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
)

START, END = "2026-09-16", "2026-09-23"


def _epoch(text: str) -> int:
    """Epoch seconds for a ``yyyy-mm-dd HH:MM`` UTC wall time."""
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def _article(headline, when, source="Reuters", url=None, summary="", related="NVDA"):
    """One Finnhub record. Headlines name the company, so the relevance gate
    admits them: these tests pin the *window*, not relevance (which has its own
    file)."""
    art = {
        "category": "company",
        "datetime": _epoch(when),
        "headline": f"{headline} — Nvidia update",
        "id": abs(hash(headline)) % 10**9,
        "related": related,
        "source": source,
        "summary": summary or f"Nvidia: {headline}.",
        "url": url or f"https://example.invalid/{abs(hash(headline)) % 10**6}",
    }
    return art


def _run(payload, **kwargs):
    """Call the adapter with a canned Finnhub body.

    ``finnhub_news`` binds ``get_config`` at import time, so the config must be
    patched on the adapter module, not on ``config``.
    """
    body = payload if isinstance(payload, str) else json.dumps(list(payload))
    kwargs.setdefault("as_of_cutoff", "2026-09-23T20:00:00Z")
    with patch.object(fn, "_request", return_value=(200, body, "")), \
            patch.object(fn, "get_api_key", return_value="test-key"), \
            patch.object(fn, "get_config",
                         return_value={"news_article_limit": 20}):
        return fn.get_news_finnhub("NVDA", START, END, **kwargs)


class TestPIT:
    def test_article_after_cutoff_is_excluded(self):
        out = _run([
            _article("Before close", "2026-09-23 14:30"),
            _article("After close scoop", "2026-09-23 21:15"),
        ])
        assert "Before close" in out
        assert "After close scoop" not in out

    def test_article_before_window_is_excluded(self):
        out = _run([_article("Too old", "2026-09-01 10:00")])
        assert "Too old" not in out
        assert "NEWS_STATUS=OUT_OF_WINDOW" in out

    def test_start_day_boundary_is_inclusive(self):
        out = _run([_article("Start day", "2026-09-16 00:00")])
        assert "Start day" in out

    def test_undated_article_is_dropped_not_guessed(self):
        art = _article("No timestamp", "2026-09-23 12:00")
        art["datetime"] = None
        out = _run([art])
        assert "No timestamp" not in out

    def test_default_cutoff_is_end_of_end_date(self):
        # No explicit cutoff: 23:58 on the analysis day is allowed, 00:01 the
        # next day is not.
        with patch.object(fn, "_request", return_value=(200, json.dumps([
            _article("Same day late", "2026-09-23 23:58"),
            _article("Next day", "2026-09-24 00:01"),
        ]), "")), \
                patch.object(fn, "get_api_key", return_value="test-key"), \
                patch.object(fn, "get_config",
                             return_value={"news_article_limit": 20}):
            out = fn.get_news_finnhub("NVDA", START, END)
        assert "Same day late" in out
        assert "Next day" not in out


class TestFormatAndDedupe:
    def test_duplicate_headlines_collapse(self):
        out = _run([
            _article("Same story", "2026-09-23 10:00", url="https://a/1"),
            _article("Same story", "2026-09-23 11:00", url="https://a/1"),
        ])
        assert out.count("### Same story") == 1

    def test_ordered_oldest_first(self):
        out = _run([
            _article("Later", "2026-09-23 18:00"),
            _article("Earlier", "2026-09-23 09:00"),
        ])
        assert out.index("Earlier") < out.index("Later")

    def test_success_header_matches_contract(self):
        out = _run([_article("Headline", "2026-09-23 12:00")])
        assert out.startswith(f"## NVDA News, from {START} to {END}")

    def test_article_keeps_source_date_and_url(self):
        out = _run([_article(
            "Headline", "2026-09-23 12:00", source="Bloomberg", url="https://b/1",
        )])
        assert "(source: Bloomberg)" in out
        assert "2026-09-23T12:00:00" in out
        assert "https://b/1" in out

    def test_limit_applies(self):
        arts = [_article(f"H{i} NVDA", f"2026-09-23 1{i}:00") for i in range(5)]
        out = _run(arts, limit=2)
        assert out.count("### H") == 2


class TestFailureClasses:
    """Failure classes must be *typed*, not text.

    Returning failure text made the vendor chain unreachable: ``route_to_vendor``
    accepts the first non-raising result as the answer, so a vendor's
    "unavailable" string stopped the next vendor from ever being asked. These
    tests therefore assert the raise, not a message.
    """

    def test_no_key_is_typed_unavailable_not_absence(self):
        from tradingagents.dataflows.errors import VendorNotConfiguredError

        # A real (empty) environment: the adapter must say "not configured"
        # rather than answer "no news".
        with patch.object(fn, "_request", return_value=(200, "[]", "")), \
                patch.object(fn, "get_config",  # noqa: SIM117
                             return_value={"news_article_limit": 20}), \
                patch.dict("os.environ", {"FINNHUB_API_KEY": ""}):
            with pytest.raises(VendorNotConfiguredError):
                fn.fetch_news_finnhub("NVDA", START, END)

    def test_rate_limit_is_typed_and_skippable(self):
        with patch.object(fn, "_request", return_value=(429, "", "")), \
                patch.object(fn, "get_api_key", return_value="test-key"), \
                patch.object(fn, "get_config",
                             return_value={"news_article_limit": 20}), \
                patch.object(fn.time, "sleep"), pytest.raises(VendorRateLimitError) as ctx:
            fn.fetch_news_finnhub("NVDA", START, END)
        assert "rate" in str(ctx.value).lower()

    def test_in_band_error_is_unavailable(self):
        out = {"error": "You don't have access to this resource."}
        with patch.object(fn, "_request", return_value=(200, json.dumps(out), "")), \
                patch.object(fn, "get_api_key", return_value="test-key"), \
                patch.object(fn, "get_config",  # noqa: SIM117
                             return_value={"news_article_limit": 20}):
            with pytest.raises(VendorUnavailableError):
                fn.fetch_news_finnhub("NVDA", START, END)

    def test_empty_feed_is_a_real_absence(self):
        out = _run([])
        assert "NEWS_STATUS=EMPTY_VALID" in out
        assert "DATA_UNAVAILABLE" not in out

    def test_unparsable_response_is_unavailable(self):
        out = _run("not json{{")
        assert "NEWS_STATUS=PARSE_ERROR" in out
        assert "No news found" not in out

    def test_network_error_is_typed_and_skippable(self):
        with patch.object(fn, "_request", return_value=(None, None, "timeout")), \
                patch.object(fn, "get_api_key", return_value="test-key"), \
                patch.object(fn, "get_config",
                             return_value={"news_article_limit": 20}), \
                patch.object(fn.time, "sleep"), pytest.raises(VendorTimeoutError):
            fn.fetch_news_finnhub("NVDA", START, END)

    def test_zero_length_output_is_never_produced(self):
        # Every path returns analyst-readable text, never "".
        for payload in ([], "{}", "garbage"):
            assert _run(payload).strip()


class TestPublicationParser:
    @pytest.mark.parametrize("raw,expected", [
        ("20260923T143000", "2026-09-23 14:30:00+00:00"),
        ("2026-09-23T14:30:00Z", "2026-09-23 14:30:00+00:00"),
        ("2026-09-23", "2026-09-23 00:00:00+00:00"),
    ])
    def test_parses_known_shapes(self, raw, expected):
        assert str(parse_publication_time(raw)) == expected

    def test_offset_is_normalised_to_utc(self):
        parsed = parse_publication_time("2026-09-23T10:30:00-04:00")
        assert str(parsed) == "2026-09-23 14:30:00+00:00"

    @pytest.mark.parametrize("raw", ["", None, "garbage", "2026-13-45"])
    def test_unparsable_returns_none(self, raw):
        assert parse_publication_time(raw) is None

    @pytest.mark.parametrize("raw,expected", [
        (1790173800, "2026-09-23 14:30:00+00:00"),   # epoch seconds
        (1790173800000, "2026-09-23 14:30:00+00:00"),  # milliseconds
        ("1790173800", "2026-09-23 14:30:00+00:00"),  # numeric string
    ])
    def test_finnhub_epoch_shapes(self, raw, expected):
        assert str(fn._parse_published(raw)) == expected

    @pytest.mark.parametrize("raw", [None, "", "garbage", 0, -5, True, {}])
    def test_finnhub_bad_epochs_are_rejected(self, raw):
        assert fn._parse_published(raw) is None


class TestRouting:
    def test_provider_chain_is_finnhub_then_gdelt(self):
        # News migration: the only registered company-news providers are the two
        # this project actually provisions. Finnhub is the symbol-specific
        # primary; GDELT supplies the global/industry coverage. The retired or
        # unprovisioned paths (Yahoo's 404 ticker endpoint, Alpha Vantage
        # NEWS_SENTIMENT) must not come back by accident.
        from tradingagents.dataflows.interface import VENDOR_METHODS
        order = list(VENDOR_METHODS["get_news"])
        # The PR #5 Release registers its own vendors as available providers;
        # the personal configured chain remains Finnhub -> GDELT (pinned by
        # `tool_vendors`), so the first two entries are the personal scope.
        assert order[:2] == ["finnhub", "gdelt"]
        assert {"finnhub", "gdelt"} <= set(order)

    def test_router_returns_string_not_exception_without_key(self):
        from tradingagents.dataflows.interface import route_to_vendor
        out = route_to_vendor("get_news", "NVDA", "2026-09-16", "2026-09-23")
        assert isinstance(out, str) and out.strip()
