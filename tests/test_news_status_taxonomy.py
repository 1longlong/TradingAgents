"""B7 — the news status taxonomy, the GDELT adapter, and the stance guard.

Campaign 20261107_140536 established three facts that these tests pin:

1. **HTTP 200 is not news.** A vendor can answer 200 with a rate-limit page, an
   auth notice, recent-only items, or nothing at all. Only
   ``SUCCESS_REAL_CONTENT`` may be read as news; every other class is an
   explicit "the vendor could not answer" and must never become Neutral.
2. **``seendate`` is not a publish time.** 4 of 5 verifiable GDELT hits with a
   2026-09-23 ``seendate`` were published 2026-09-22. A GDELT adapter that
   trusts ``seendate`` puts yesterday's news in today's prompt.
3. **A failure must be typed, not text.** Returning failure text made the vendor
   chain unreachable: the router accepts the first non-raising result.

Everything here is offline: transports are patched. The live behaviour is
recorded in ``probes/PROBE_LOG.md`` and ``evidence/``.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tradingagents.agents.schemas import (
    NewsSourceStatus,
    classify_news_source_availability,
)
from tradingagents.dataflows import gdelt_news as gn
from tradingagents.dataflows.errors import (
    VendorRateLimitError,
    VendorTimeoutError,
    VendorUnavailableError,
)
from tradingagents.dataflows.news_status import (
    CLASSES,
    PROVES_REAL_NEWS,
    TRANSIENT,
    NewsStatus,
    render_status,
)

START, END = "2026-09-23", "2026-09-23"


# --------------------------------------------------------------------------
# 1. The taxonomy itself
# --------------------------------------------------------------------------


class TaxonomyTest(unittest.TestCase):
    """Exactly twelve classes, one meaning each."""

    def test_exactly_twelve_classes(self):
        self.assertEqual(len(CLASSES), 12)

    def test_class_names_are_exactly_the_contract(self):
        expected = {
            "SUCCESS_REAL_CONTENT", "EMPTY_VALID", "HISTORICAL_UNSUPPORTED",
            "OUT_OF_WINDOW", "AUTH_MISSING", "AUTH_INVALID", "RATE_LIMITED",
            "TIMEOUT", "PROVIDER_UNAVAILABLE", "HTTP_ERROR", "PARSE_ERROR",
            "CONFIG_DISABLED",
        }
        self.assertEqual({c.value for c in CLASSES}, expected)

    def test_only_success_asserts_real_news(self):
        self.assertEqual(PROVES_REAL_NEWS, frozenset({NewsStatus.SUCCESS_REAL_CONTENT}))

    def test_permanent_classes_are_not_retried(self):
        for permanent in (
            NewsStatus.AUTH_MISSING, NewsStatus.AUTH_INVALID,
            NewsStatus.PROVIDER_UNAVAILABLE, NewsStatus.HISTORICAL_UNSUPPORTED,
            NewsStatus.CONFIG_DISABLED,
        ):
            with self.subTest(status=permanent.value):
                self.assertNotIn(permanent, TRANSIENT)

    def test_missing_credentials_and_retired_endpoints_are_distinct(self):
        self.assertIsNot(NewsStatus.AUTH_MISSING, NewsStatus.PROVIDER_UNAVAILABLE)
        self.assertIsNot(NewsStatus.EMPTY_VALID, NewsStatus.OUT_OF_WINDOW)

    def test_every_failure_class_renders_its_own_token(self):
        for status in CLASSES:
            if status is NewsStatus.SUCCESS_REAL_CONTENT:
                continue
            with self.subTest(status=status.value):
                text = render_status(status, vendor="V", subject="NVDA",
                                     start_date=START, end_date=END, detail="d")
                self.assertTrue(text.startswith(f"NEWS_STATUS={status.value}"), text)

    def test_only_empty_valid_speaks_about_the_instrument(self):
        # Every other class is a fact about the vendor, which is why it cannot
        # be reported as "NVDA was quiet".
        for status in CLASSES:
            if status in (NewsStatus.SUCCESS_REAL_CONTENT, NewsStatus.EMPTY_VALID):
                continue
            with self.subTest(status=status.value):
                text = render_status(status, vendor="V", subject="NVDA",
                                     start_date=START, end_date=END)
                self.assertIn("says nothing about the instrument", text)
                self.assertNotIn("no articles about", text)

    def test_render_status_refuses_success(self):
        with self.assertRaises(ValueError):
            render_status(NewsStatus.SUCCESS_REAL_CONTENT, vendor="V",
                          subject="NVDA", start_date=START, end_date=END)


# --------------------------------------------------------------------------
# 2. GDELT: discovery, not truth
# --------------------------------------------------------------------------


def _gdelt_payload(*articles):
    return json.dumps({"articles": list(articles)})


def _hit(title, url, seendate="20260923T120000Z", domain="example.com"):
    return {"title": title, "url": url, "seendate": seendate, "domain": domain}


class GdeltPublishTimeTest(unittest.TestCase):
    """``seendate`` must never be used as the publication time."""

    def test_jsonld_date_published_wins(self):
        page = '<html><script>{"datePublished": "2026-09-22T14:30:44Z"}</script></html>'
        published, method = gn.extract_publish_time(page)
        self.assertEqual(method, "json-ld datePublished")
        self.assertEqual(published, datetime(2026, 9, 22, 14, 30, 44, tzinfo=timezone.utc))

    def test_meta_published_time_is_used_when_no_jsonld(self):
        page = ('<meta property="article:published_time" '
                'content="2026-09-23T04:00:00Z">')
        published, method = gn.extract_publish_time(page)
        self.assertEqual(method, "meta published_time")
        self.assertEqual(published.day, 23)

    def test_time_element_is_last_resort(self):
        page = '<time datetime="2026-09-23T05:30:00Z">x</time>'
        published, method = gn.extract_publish_time(page)
        self.assertEqual(method, "<time datetime>")

    def test_page_without_timestamp_yields_none(self):
        self.assertEqual(gn.extract_publish_time("<html>no dates</html>"), (None, ""))

    def test_there_is_no_seendate_parser_to_mistake_for_publish_time(self):
        # seendate is an index time, not a publication time. The campaign
        # deliberately provides no parser for it so no caller can be tempted to
        # use it (audit D-3).
        self.assertFalse(hasattr(gn, "_parse_seendate"))


class GdeltWindowTest(unittest.TestCase):
    """A GDELT hit indexed on the target day but published the day before is dropped."""

    def test_article_published_the_day_before_is_excluded(self):
        payload = _gdelt_payload(_hit("Nvidia price prediction", "https://x/nvda-1"))
        # seendate says 09-23; the publisher says 09-22. The publisher wins.
        page = '<script>{"datePublished": "2026-09-22T14:30:44Z"}</script>'
        with patch.object(gn, "_request", return_value=(200, payload, "")), \
             patch.object(gn, "_fetch_page", return_value=(200, page, "")), \
             patch.object(gn, "_throttle"):
            out = gn.get_news_gdelt("NVDA", START, END)
        self.assertNotIn("price prediction", out)
        self.assertIn("NEWS_STATUS=OUT_OF_WINDOW", out)

    def test_article_published_inside_the_day_is_kept(self):
        payload = _gdelt_payload(_hit("Nvidia ships", "https://x/nvda-2"))
        page = '<script>{"datePublished": "2026-09-23T04:00:00Z"}</script>'
        with patch.object(gn, "_request", return_value=(200, payload, "")), \
             patch.object(gn, "_fetch_page", return_value=(200, page, "")), \
             patch.object(gn, "_throttle"):
            out = gn.get_news_gdelt("NVDA", START, END)
        self.assertIn("Nvidia ships", out)
        self.assertIn("2026-09-23T04:00:00+00:00", out)
        self.assertIn("https://x/nvda-2", out)
        self.assertNotIn("NEWS_STATUS=", out)

    def test_unverifiable_page_is_dropped_not_assumed(self):
        payload = _gdelt_payload(_hit("Nvidia rumor", "https://x/nvda-3"))
        with patch.object(gn, "_request", return_value=(200, payload, "")), \
             patch.object(gn, "_fetch_page", return_value=(404, None, "")), \
             patch.object(gn, "_throttle"):
            out = gn.get_news_gdelt("NVDA", START, END)
        self.assertNotIn("Nvidia rumor", out)
        self.assertIn("OUT_OF_WINDOW", out)

    def test_irrelevant_hit_is_not_ticker_news(self):
        payload = _gdelt_payload(_hit("Unrelated story", "https://x/other"))
        with patch.object(gn, "_request", return_value=(200, payload, "")), \
             patch.object(gn, "_fetch_page", return_value=(200, "", "")), \
             patch.object(gn, "_throttle"):
            out = gn.get_news_gdelt("NVDA", START, END)
        self.assertIn("EMPTY_VALID", out)


class GdeltFailureTest(unittest.TestCase):
    """Each transport outcome maps to its own class, never to 'no news'.

    Request-level failures must RAISE so the router can try the next vendor;
    only answer-level outcomes (empty, out-of-window, unsupported window) are
    returned as text.
    """

    def _call(self, http_status, body, kind=""):
        with patch.object(gn, "_request", return_value=(http_status, body, kind)), \
             patch.object(gn, "_throttle"), \
             patch.object(gn, "_MAX_ATTEMPTS", 1):
            return gn.get_news_gdelt("NVDA", START, END)

    def test_429_is_rate_limited_not_empty(self):
        with self.assertRaises(VendorRateLimitError) as ctx:
            self._call(429, "Please limit requests to one every 5 seconds")
        self.assertIn("rate_limited", str(ctx.exception))

    def test_timeout_is_typed(self):
        # Strengthened (audit W7): a socket timeout used to be folded into
        # VendorRateLimitError, making it indistinguishable from a 429. It now
        # has its own class.
        with self.assertRaises(VendorTimeoutError) as ctx:
            self._call(None, None, "timeout")
        self.assertNotIsInstance(ctx.exception, VendorRateLimitError)
        self.assertIn("timeout", str(ctx.exception))

    def test_404_is_permanently_unavailable(self):
        with self.assertRaises(VendorUnavailableError):
            self._call(404, None)

    def test_500_is_retryable(self):
        # A 5xx is an HTTP failure, not a throttle (audit W7 keeps the two
        # apart); it is still a VendorUnavailableError, so the router fails over
        # exactly as before.
        with self.assertRaises(VendorUnavailableError) as ctx:
            self._call(500, None)
        self.assertNotIsInstance(ctx.exception, VendorTimeoutError)

    def test_non_json_body_is_parse_error(self):
        with self.assertRaises(VendorUnavailableError):
            self._call(200, "<html>nope</html>")

    def test_missing_articles_key_is_a_real_empty_answer(self):
        self.assertIn("EMPTY_VALID", self._call(200, json.dumps({})))

    def test_window_older_than_archive_never_requests(self):
        # GDELT archives ~3 months; asking is pointless and the answer would
        # read as an absence. It must be refused locally, without a call.
        with patch.object(gn, "_request") as request:
            out = gn.get_news_gdelt("NVDA", "2025-01-01", "2025-01-31")
        request.assert_not_called()
        self.assertIn("HISTORICAL_UNSUPPORTED", out)

    def test_end_datetime_covers_the_whole_end_day(self):
        # GDELT rejects a zero-length interval: ENDDATETIME must be the last
        # second of the end day, not its midnight (measured 2026-11-08).
        seen = {}

        def _capture(url):
            seen["url"] = url
            return 200, json.dumps({}), ""

        with patch.object(gn, "_request", side_effect=_capture), \
             patch.object(gn, "_throttle"):
            gn.get_news_gdelt("NVDA", "2026-09-23", "2026-09-23")
        self.assertIn("startdatetime=20260923000000", seen["url"])
        self.assertIn("enddatetime=20260923235959", seen["url"])

    def test_invalid_query_body_is_not_a_parse_error(self):
        with patch.object(gn, "_request", return_value=(200, "Invalid query end date.", "")), \
             patch.object(gn, "_throttle"), patch.object(gn, "_MAX_ATTEMPTS", 1):
            # Audit W7: an unparsable/invalid body is HTTP_ERROR, i.e.
            # VendorUnavailableError, NOT a throttle. Still fails over.
            with self.assertRaises(VendorUnavailableError) as ctx:
                gn.get_news_gdelt("NVDA", START, END)
        self.assertIn("http_error", str(ctx.exception))
        self.assertNotIn("parse_error", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, VendorTimeoutError)
        with patch.object(gn, "_request", return_value=(429, "", "")) as request, \
             patch.object(gn, "_throttle"):
            with self.assertRaises(VendorRateLimitError):
                gn.get_news_gdelt("NVDA", START, END)
        self.assertLessEqual(request.call_count, 2)

    def test_a_gdelt_failure_does_not_mask_later_vendors(self):
        # The live defect: GDELT returned failure *text*, the router accepted it
        # as the answer, and yfinance was never asked.
        from tradingagents.dataflows import yfinance_news as yn
        from tradingagents.dataflows import interface as iface

        class _Ticker:
            def __init__(self, symbol):
                pass

            def get_news(self, count=0):
                raise AssertionError("reached yfinance")

        with patch.object(gn, "_request", return_value=(429, "", "")), \
             patch.object(gn, "_throttle"), \
             patch.object(yn.yf, "Ticker") as ticker:
            ticker.side_effect = yn.YFDataException("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***")
            out = iface.route_to_vendor("get_news", "NVDA", START, END)
        # Both vendors failed, so the router answers for the whole chain rather
        # than the first vendor's own string.
        self.assertIn("DATA_UNAVAILABLE", out)

    def test_a_socket_timeout_is_not_a_throttle_and_still_fails_over(self):
        # Audit W7: a timeout must be its own type; the router must still ask the
        # next vendor and, when none serves, still end in DATA_UNAVAILABLE.
        from tradingagents.dataflows import interface as iface
        from tradingagents.dataflows import yfinance_news as yn

        asked = []

        class _Ticker:
            def __init__(self, symbol):
                pass

            def get_news(self, count=0):
                asked.append("yfinance")
                raise yn.YFDataException("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***")

        # 1) The adapter itself raises the timeout class.
        with patch.object(gn, "_request", return_value=(None, None, "timeout")), \
             patch.object(gn, "_throttle"), \
             patch.object(gn, "_MAX_ATTEMPTS", 1):
            with pytest.raises(VendorTimeoutError) as ctx:
                gn.get_news_gdelt("NVDA", START, END)
        self.assertNotIsInstance(ctx.value, VendorRateLimitError)

        # 2) Through the router: GDELT is not accepted as an answer, the next
        #    vendor is asked, and the chain ends in the sentinel.
        with patch.dict(iface.VENDOR_METHODS["get_news"], clear=False), \
             patch.object(gn, "_request", return_value=(None, None, "timeout")), \
             patch.object(gn, "_throttle"), \
             patch.object(gn, "_MAX_ATTEMPTS", 1), \
             patch.object(yn.yf, "Ticker") as ticker:
            ticker.side_effect = _Ticker
            iface.VENDOR_METHODS["get_news"]["gdelt"] = gn.get_news_gdelt
            try:
                out = iface.route_to_vendor("get_news", "NVDA", START, END)
            except Exception as routed_exc:  # noqa: BLE001
                out = f"RAISED {type(routed_exc).__name__}: {routed_exc}"
        self.assertTrue(asked, "the router did not try the next vendor after a timeout")
        self.assertIn("DATA_UNAVAILABLE", out)
        self.assertNotIn("RATE_LIMIT", out)
        self.assertNotIn("VendorRateLimitError", out)


# --------------------------------------------------------------------------
# 3. The stance guard: no news must never become Neutral/Mixed
# --------------------------------------------------------------------------


class _ToolMsg:
    def __init__(self, name, content):
        self.type = "tool"
        self.name = name
        self.content = content


class NewsAvailabilityTest(unittest.TestCase):
    """B7: all ticker news unavailable (macro present) => source UNAVAILABLE."""

    def test_every_failure_class_counts_as_unavailable(self):
        macro = _ToolMsg("get_macro_indicators_batch", "## FRED\nCPI 3.1%")
        for status in CLASSES:
            if status is NewsStatus.SUCCESS_REAL_CONTENT:
                continue
            with self.subTest(status=status.value):
                news = _ToolMsg(
                    "get_news",
                    render_status(status, vendor="GDELT", subject="NVDA",
                                  start_date=START, end_date=END),
                )
                self.assertEqual(
                    classify_news_source_availability([news, macro]),
                    NewsSourceStatus.UNAVAILABLE,
                )

    def test_success_with_real_content_is_available(self):
        news = _ToolMsg("get_news", "## NVDA News\n\n### Nvidia ships (source: x)")
        self.assertEqual(
            classify_news_source_availability([news]),
            NewsSourceStatus.AVAILABLE,
        )

    def test_macro_alone_never_makes_news_available(self):
        macro = _ToolMsg("get_macro_indicators_batch", "## FRED\nCPI 3.1%")
        self.assertEqual(
            classify_news_source_availability([macro]),
            NewsSourceStatus.UNAVAILABLE,
        )

    # --- audit D-1: absence must never read as presence ---------------------

    def test_empty_content_is_unavailable(self):
        for content in ("", "   ", "\n\n"):
            with self.subTest(content=repr(content)):
                self.assertEqual(
                    classify_news_source_availability([_ToolMsg("get_news", content)]),
                    NewsSourceStatus.UNAVAILABLE,
                )

    def test_header_only_render_is_unavailable(self):
        header = "## NVDA News, from 2026-09-23 to 2026-09-23:\n\n0 article(s):\n\n"
        self.assertEqual(
            classify_news_source_availability([_ToolMsg("get_news", header)]),
            NewsSourceStatus.UNAVAILABLE,
        )

    def test_prose_without_articles_is_unavailable(self):
        prose = "Nothing notable happened for NVDA in this window."
        self.assertEqual(
            classify_news_source_availability([_ToolMsg("get_news", prose)]),
            NewsSourceStatus.UNAVAILABLE,
        )

    def test_yfinance_no_news_found_is_unavailable(self):
        # yfinance's own absence wording carries no NEWS_STATUS token; before
        # audit D-1 it classified as AVAILABLE.
        text = "No news found for NVDA between 2026-09-16 and 2026-09-23 (vendor returned no articles in the window)."
        self.assertEqual(
            classify_news_source_availability([_ToolMsg("get_news", text)]),
            NewsSourceStatus.UNAVAILABLE,
        )

    def test_absence_plus_macro_is_still_unavailable(self):
        macro = _ToolMsg("get_macro_indicators_batch", "## FRED\nCPI 3.1%")
        news = _ToolMsg("get_news", "")
        self.assertEqual(
            classify_news_source_availability([news, macro]),
            NewsSourceStatus.UNAVAILABLE,
        )

    def test_raw_alpha_vantage_json_feed_is_available(self):
        # The raw AV adapter returns JSON, not markdown; a real feed is news.
        payload = json.dumps({"feed": [{"title": "Nvidia ships", "url": "https://x/1"}]})
        self.assertEqual(
            classify_news_source_availability([_ToolMsg("get_news", payload)]),
            NewsSourceStatus.AVAILABLE,
        )

    def test_raw_alpha_vantage_empty_feed_is_unavailable(self):
        self.assertEqual(
            classify_news_source_availability([_ToolMsg("get_news", json.dumps({"feed": []}))]),
            NewsSourceStatus.UNAVAILABLE,
        )


    def test_legacy_unavailable_markers_still_honoured(self):
        news = _ToolMsg("get_news", "DATA_UNAVAILABLE: nope")
        self.assertEqual(
            classify_news_source_availability([news]),
            NewsSourceStatus.UNAVAILABLE,
        )


if __name__ == "__main__":
    unittest.main()
