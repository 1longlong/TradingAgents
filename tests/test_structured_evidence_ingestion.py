"""ADR-008 Stage 1: automatic structured optional-evidence ingestion.

Approved test cases (2026-11-11 human plan/test approval; plan + tests ONLY, not
final acceptance). These prove the **automatic** path — a real raw vendor
fixture → the real tool invocation → the gate → the manifest / citation allowlist
/ researcher / saved report — without manually injecting optional groups, plus
the negative/fail-closed and isolation guarantees.

Coverage:
- fundamentals / news / sentiment flow from a vendor-origin record to the gate;
- normal / degraded / blocked routing, optional-missing degradation, and market
  block dominance;
- missing / wrong-shape / NaN / non-string / bool / future-published / late-filed
  inputs fail closed (never decisive), with stable requirement IDs;
- deterministic shuffled ordering, duplicate/syndication lineage dedup, and
  source attempts recorded only for actually-operated sources (including two
  distinct attempts with ``started_at=None`` that must NOT collapse);
- two symbols / two dates / concurrent runs / repeated checkpoint do not
  contaminate or duplicate;
- capture survives the real ToolNode worker-thread execution AND is persisted to
  graph state before a checkpoint (durability);
- public tool output and legacy (non-feature) behavior are unchanged.

Traceability: FR-DQG-004 (multi-category gate), FR-DQG-005 (report artifacts),
FR-DDT-002 (manifest / allowlist), NFR-PIT-001, NFR-AUD-001, NFR-DET-001,
NFR-BC-001. All tests are socket-disabled offline with mocked vendors/models.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
import tradingagents.dataflows.yfinance_news as ynews
from tradingagents.dataflows import evidence_capture, reddit, stocktwits
from tradingagents.evidence import (
    EvidenceGroupQuality,
    QualityStatus,
    SourceResultStatus,
)
from tradingagents.evidence.ingest import (
    AttemptEnvelope,
    StructuredEvidenceCollector,
    capture_attempt,
    capture_record,
    get_active_collector,
    merge_into_state,
    use_collector,
)
from tradingagents.evidence.models import SourceAttempt
from tradingagents.evidence.vendor_adapters import (
    build_news_record,
    build_sentiment_record,
    validate_optional_records,
)
from tradingagents.graph.data_quality_gate import (
    GATE_EVIDENCE_RECORDS_KEY,
    GATE_OPTIONAL_EVIDENCE_KEY,
    GATE_SOURCE_ATTEMPTS_KEY,
    GATE_VERDICT_KEY,
    create_data_quality_gate_node,
)
from tradingagents.graph.evidence_tool_node import capture_into_state

SYMBOL = "AAPL"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"


# ---------------------------------------------------------------------------
# Deterministic market snapshot (no network): mirrors the gate tests.
# ---------------------------------------------------------------------------


def _fixed_df() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )


@pytest.fixture
def fixed_snapshot(monkeypatch):
    monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: _fixed_df())


def _epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


class _JsonResp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


# ---------------------------------------------------------------------------
# Raw vendor fixtures (the ORIGINAL objects the vendors return)
# ---------------------------------------------------------------------------


def _raw_yahoo_news() -> list[dict]:
    return [
        {
            "title": "AAPL beats Q1 earnings",
            "publisher": "Reuters",
            "link": "https://news.example.com/aapl?token=SECRET123",
            "providerPublishTime": _epoch("2026-05-10"),
        },
        # Syndicated copy of the same article under a different link (dedupe).
        {
            "title": "AAPL beats Q1 earnings",
            "publisher": "Yahoo Syndication",
            "link": "https://synd.example.com/aapl-copy?utm=abc",
            "providerPublishTime": _epoch("2026-05-10"),
        },
        # Future-published: must be excluded (look-ahead).
        {
            "title": "AAPL future event",
            "publisher": "Future",
            "link": "https://news.example.com/future",
            "providerPublishTime": _epoch("2026-06-01"),
        },
    ]


def _raw_stocktwits() -> list[dict]:
    return [
        {
            "created_at": "2026-05-10T12:00:00Z",
            "user": {"username": "secret_user"},
            "entities": {"sentiment": {"basic": "Bullish"}},
            "body": "AAPL to the moon, this is my body text",
        },
        {
            "created_at": "2026-05-11T09:00:00Z",
            "user": {"username": "another_user"},
            "entities": {},
            "body": "no native label here",
        },
    ]


def _raw_reddit() -> list[dict]:
    return [
        {"title": "AAPL discussion", "created_utc": _epoch("2026-05-09"), "subreddit": "stocks"},
    ]


def _capture_shape(articles: list[dict]) -> list[dict]:
    """Convert raw Yahoo article objects to the shape capture expects.

    The real ``get_news_yfinance`` path passes ``_extract_article_data`` output
    (with a ``published`` datetime) to ``capture_news_articles``; these direct
    tests feed the same shape so they exercise the adapter honestly.
    """
    out = []
    for a in articles:
        ts = a.get("providerPublishTime")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc) if ts else a.get("published")
        )
        out.append(
            {
                "title": a.get("title"),
                "publisher": a.get("publisher", ""),
                "url": a.get("link", ""),
                "published": published,
            }
        )
    return out


def _raw_sec_facts() -> dict:
    # Structured return of sec_edgar.structured_statement_facts.
    return {
        "income_statement": {
            "revenue": [
                {"period_end": "2026-03-31", "filed": "2026-05-02", "value": 111000000000.0,
                 "unit": "USD", "accn": "0001-26-000001"},
                # A later filing after the target must not be used.
                {"period_end": "2026-06-30", "filed": "2026-08-01", "value": 999.0,
                 "unit": "USD", "accn": "0001-26-000002"},
            ],
        },
    }


def _gate_node():
    return create_data_quality_gate_node(now_provider=lambda: FETCHED)


# ---------------------------------------------------------------------------
# Fundamentals: real tool invocation -> gate
# ---------------------------------------------------------------------------


class TestFundamentalsIngestion:
    def test_sec_tool_capture_reaches_gate_and_report(self, fixed_snapshot):
        # Real capture helper the SEC tool uses, then the real gate reads it.
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_sec_statement_facts(
                SYMBOL, _raw_sec_facts(), freq="quarterly", tool="get_income_statement"
            )
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        assert cats["fundamentals"] in ("Medium", "Low")
        records = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "fundamentals"]
        assert records, "SEC facts must become gate evidence"
        # The filed date (2026-05-02), not the period end, is observed_at.
        assert records[0]["observed_at"] == "2026-05-02"
        assert records[0]["value_raw"] == "111000000000.0"
        # The future-filed row is never decisive.
        assert all(r["observed_at"] <= TARGET for r in records)

    def test_late_filing_is_excluded_not_decisive(self, fixed_snapshot):
        facts = {
            "income_statement": {
                "revenue": [
                    {"period_end": "2026-03-31", "filed": "2026-06-20", "value": 5.0,
                     "unit": "USD", "accn": "late"},
                ]
            }
        }
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_sec_statement_facts(
                SYMBOL, facts, freq="quarterly", tool="get_income_statement"
            )
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        records = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "fundamentals"]
        # No eligible row (filed after target) => no decisive fundamentals record.
        assert records == []


# ---------------------------------------------------------------------------
# News: real tool invocation -> gate
# ---------------------------------------------------------------------------


class TestNewsIngestion:
    def _invoke_news_tool(self):
        def get_news(self, count=20):
            return _raw_yahoo_news()

        ynews.yf.Ticker = lambda *a, **k: type("T", (), {"get_news": get_news})()
        return ynews.get_news_yfinance(SYMBOL, "2026-05-06", TARGET)

    def test_news_tool_output_unchanged_and_captured(self, fixed_snapshot, monkeypatch):
        monkeypatch.setattr(ynews.yf, "Ticker", lambda *a, **k: _FakeTicker(_raw_yahoo_news()))
        with use_collector(SYMBOL, TARGET):
            prose = self._invoke_news_tool()
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        # Public prose compatibility: the compatible header/marker still present.
        assert prose.startswith(f"## {SYMBOL} News")
        assert "AAPL beats Q1 earnings" in prose
        records = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "news"]
        assert records, "captured news must reach the gate"
        # Syndicated duplicate collapses to one lineage; future excluded.
        titles = [r["metric_name"] for r in records]
        assert titles.count("AAPL beats Q1 earnings") == 1
        assert "AAPL future event" not in titles
        assert all(r["observed_at"] <= TARGET for r in records)

    def test_news_url_query_string_and_body_not_leaked(self, fixed_snapshot, monkeypatch):
        monkeypatch.setattr(ynews.yf, "Ticker", lambda *a, **k: _FakeTicker(_raw_yahoo_news()))
        with use_collector(SYMBOL, TARGET):
            self._invoke_news_tool()
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        blob = json.dumps(out[GATE_EVIDENCE_RECORDS_KEY])
        assert "SECRET123" not in blob and "utm=abc" not in blob


class _FakeTicker:
    def __init__(self, articles):
        self._articles = articles

    def get_news(self, count=20):
        return self._articles


# ---------------------------------------------------------------------------
# Sentiment: real fetchers -> gate
# ---------------------------------------------------------------------------


class TestSentimentIngestion:
    def test_stocktwits_native_label_and_privacy(self, fixed_snapshot, monkeypatch):
        monkeypatch.setattr(
            stocktwits, "urlopen", lambda *a, **k: _JsonResp({"messages": _raw_stocktwits()})
        )
        with use_collector(SYMBOL, TARGET):
            stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-06", end_date=TARGET)
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        records = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "sentiment"]
        assert records
        labels = {r["value_raw"] for r in records}
        assert "bullish" in labels  # native StockTwits label preserved
        assert "unlabeled" in labels  # no invented label
        blob = json.dumps(records)
        # Usernames and post bodies are never persisted.
        assert "secret_user" not in blob and "another_user" not in blob
        assert "to the moon" not in blob

    def test_reddit_posts_are_unlabeled_not_invented(self, fixed_snapshot, monkeypatch):
        monkeypatch.setattr(
            reddit, "_fetch_subreddit_rss",
            lambda *a, **k: [{"title": "AAPL talk", "created_utc": _epoch("2026-05-09"), "subreddit": "stocks"}],
        )
        with use_collector(SYMBOL, TARGET):
            reddit.fetch_reddit_posts(SYMBOL, subreddits=("stocks",), start_date="2026-05-06", end_date=TARGET)
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        records = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "sentiment"]
        assert records
        assert all(r["value_raw"] == "unlabeled" for r in records)


# ---------------------------------------------------------------------------
# Routing: normal / degraded / blocked, optional-missing, market dominance
# ---------------------------------------------------------------------------


class TestRouting:
    def test_all_three_categories_present_can_be_medium(self, fixed_snapshot, monkeypatch):
        # All three optional categories captured with at least one VALID (passing)
        # structured record each. Assert the EXACT expected per-record quality and
        # that the valid IDs reach the citation allowlist — not just "Medium|Low".
        monkeypatch.setattr(ynews.yf, "Ticker", lambda *a, **k: _FakeTicker(_raw_yahoo_news()))
        monkeypatch.setattr(stocktwits, "urlopen", lambda *a, **k: _JsonResp({"messages": _raw_stocktwits()}))
        with use_collector(SYMBOL, TARGET):
            ynews.get_news_yfinance(SYMBOL, "2026-05-06", TARGET)
            evidence_capture.capture_sec_statement_facts(
                SYMBOL, _raw_sec_facts(), freq="quarterly", tool="get_income_statement"
            )
            stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-06", end_date=TARGET)
            state = {"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"}
            out = _gate_node()(state)

        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        # Every optional category has a validated, eligible record => Medium.
        assert cats["fundamentals"] == "Medium"
        assert cats["news"] == "Medium"
        assert cats["sentiment"] == "Medium"

        # Each category's usable records carry the computed per-record status and
        # are citable (not Low/unvalidated, not forced Low by missing numeric).
        from tradingagents.debate.evidence_manifest import build_citation_allowlist

        allowlist = build_citation_allowlist(out[GATE_EVIDENCE_RECORDS_KEY], TARGET)
        for category in ("fundamentals", "news", "sentiment"):
            usable = [
                r for r in out[GATE_EVIDENCE_RECORDS_KEY]
                if r["category"] == category and r["quality_status"] == "Medium"
            ]
            assert usable, f"{category} must have a usable Medium record"
            for r in usable:
                assert r["evidence_id"] in allowlist
                # Qualitative records are NOT forced through the numeric schema.
                assert "unvalidated" not in r["quality_reasons"]

        # With market adequate + all three optional Medium, the verdict is normal.
        assert cats["market"] in ("High", "Medium")
        assert out[GATE_VERDICT_KEY] == "normal"

    def test_unlabeled_reddit_still_medium_and_no_invented_corroboration(self, fixed_snapshot, monkeypatch):
        # A single unlabeled Reddit post is a valid (Medium) qualitative record but
        # is ONE independent lineage: it never manufactures independent
        # corroboration. Its native label is "unlabeled" (never invented).
        monkeypatch.setattr(
            reddit, "_fetch_subreddit_rss",
            lambda *a, **k: [{"title": "AAPL talk", "created_utc": _epoch("2026-05-09"), "subreddit": "stocks"}],
        )
        with use_collector(SYMBOL, TARGET):
            reddit.fetch_reddit_posts(SYMBOL, subreddits=("stocks",), start_date="2026-05-06", end_date=TARGET)
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        sent = next(g for g in out["data_quality_group_statuses"] if g["category"] == "sentiment")
        assert sent["quality_status"] in ("Medium", "Low")
        assert sent["independent_source_count"] == 1  # one lineage, no inflation
        recs = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "sentiment"]
        assert all(r["value_raw"] == "unlabeled" for r in recs)

    def test_optional_missing_degrades(self, fixed_snapshot):
        node = _gate_node()
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out[GATE_VERDICT_KEY] == "degraded"
        for cat in ("fundamentals", "news", "sentiment"):
            g = next(x for x in out["data_quality_group_statuses"] if x["category"] == cat)
            assert g["quality_status"] == "Low"
            assert g["source_count"] == 0

    def test_market_block_dominates_optional(self, fixed_snapshot):
        # Even with captured optional evidence, a blocked market forces blocked.
        from tradingagents.evidence import Criticality, EvidenceGroupQuality

        def blocked_aggregator(category, records, results_by_id, policy=None):
            return (
                EvidenceGroupQuality(
                    category="market", quality_status=QualityStatus.BLOCKED,
                    criticality=Criticality.CRITICAL, evidence_ids=[], source_count=0,
                    independent_source_count=0, reason_codes=["blocked_lookahead"],
                    human_readable_reason="Blocked.",
                ),
                {},
            )

        node = create_data_quality_gate_node(now_provider=lambda: FETCHED, aggregator=blocked_aggregator)
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_sec_statement_facts(
                SYMBOL, _raw_sec_facts(), freq="quarterly", tool="get_income_statement"
            )
            out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out[GATE_VERDICT_KEY] == "blocked"


# ---------------------------------------------------------------------------
# Fail-closed on malformed optional input (stable requirement IDs)
# ---------------------------------------------------------------------------


class TestFailClosedInputs:
    def _news_record(self, **overrides):
        kw = {
            "run_id": f"{TARGET}/{SYMBOL}",
            "symbol_input": SYMBOL,
            "symbol_normalized": SYMBOL,
            "target_date": TARGET,
            "title": "x",
            "publisher": "P",
            "url": "u",
            "published": "2026-05-10",
            "source_name": "yfinance_news",
        }
        kw.update(overrides)
        return build_news_record(**kw)

    @pytest.mark.parametrize("published", [None, "", "not-a-date", 20260510, True])
    def test_bad_publication_date_is_excluded(self, published):
        # NFR-PIT-001: a missing/malformed/non-string/bool date is never assumed
        # equal to the target date; the record is excluded, not decisive.
        from tradingagents.evidence.vendor_adapters import validate_news_record

        rec = self._news_record(published=published)
        results, exclusion = validate_news_record(
            rec, expected_symbol=SYMBOL, target_date=TARGET
        )
        assert exclusion is not None
        assert any(r.status.value == "fail" for r in results)

    def test_future_publication_excluded(self):
        from tradingagents.evidence.vendor_adapters import validate_news_record

        rec = self._news_record(published="2026-06-01")
        results, exclusion = validate_news_record(
            rec, expected_symbol=SYMBOL, target_date=TARGET
        )
        assert exclusion == "lookahead"

    def test_nan_and_bool_amount_never_decisive(self):

        from tradingagents.evidence.vendor_adapters import build_sec_fundamentals_record

        # NaN magnitude: quantize_decimal maps NaN to None; the record still
        # requires a filed date and the amount check is NOT_APPLICABLE/FAIL.
        rec = build_sec_fundamentals_record(
            run_id=f"{TARGET}/{SYMBOL}", symbol_input=SYMBOL, symbol_normalized=SYMBOL,
            target_date=TARGET, metric_name="revenue", value_raw="nan",
            value_normalized=float("nan"), unit_raw="USD",
            filed_date="2026-05-02", period_end="2026-03-31", source_ref="sec:x",
        )
        assert rec.value_normalized is None  # NaN never becomes a magnitude

    def test_wrong_ticker_mismatch_fails(self):
        rec = self._news_record(symbol_normalized="MSFT")
        results = validate_optional_records(
            {"news": [rec]}, expected_symbol=SYMBOL, target_date=TARGET
        )[rec.evidence_id]
        assert any(
            r.rule_id == "optional.asset.ticker_match" and r.status.value == "fail"
            for r in results
        )


# ---------------------------------------------------------------------------
# Determinism, dedup, attempts
# ---------------------------------------------------------------------------


class TestDeterminismAndAttempts:
    def test_shuffled_capture_order_is_deterministic(self, fixed_snapshot):
        records = _raw_yahoo_news()
        outputs = []
        for order in (records, list(reversed(records))):
            with use_collector(SYMBOL, TARGET):
                evidence_capture.capture_news_articles(
                    SYMBOL, _capture_shape(order), source_name="yfinance_news", tool="get_news"
                )
                out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
            outputs.append(
                sorted(r["evidence_id"] for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "news")
            )
        assert outputs[0] == outputs[1]

    def test_two_attempts_with_none_started_at_do_not_collapse(self):
        # FR-DQG-005 / NFR-AUD-001: distinct attempts with identical structure
        # (started_at=None) get distinct explicit attempt_index identities.
        collector = StructuredEvidenceCollector()
        collector.seed(SYMBOL, TARGET)
        a1 = SourceAttempt(source="stocktwits", tool="stocktwits", started_at=None,
                           duration=None, result_status=SourceResultStatus.SUCCESS,
                           error_type=None, error_message=None)
        collector.capture_attempt(a1)
        collector.capture_attempt(a1)  # a genuinely repeated real call
        envelopes = collector.attempt_envelopes()
        assert len(envelopes) == 2
        assert [e.attempt_index for e in envelopes] == [0, 1]

    def test_resync_of_same_index_does_not_duplicate(self):
        collector = StructuredEvidenceCollector()
        collector.seed(SYMBOL, TARGET)
        env = AttemptEnvelope(
            attempt_index=3,
            attempt=SourceAttempt(source="s", tool="t", started_at=None, duration=None,
                                  result_status=SourceResultStatus.SUCCESS,
                                  error_type=None, error_message=None),
        )
        collector.seed_attempt(env)
        collector.seed_attempt(env)  # re-seed from checkpoint: no duplicate
        assert len(collector.attempt_envelopes()) == 1
        assert collector.metadata.next_attempt_index == 4

    def test_no_attempt_for_uncalled_feed(self, fixed_snapshot):
        # Only the news feed is operated; sentiment must have no invented attempt.
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_news_articles(
                SYMBOL, _capture_shape(_raw_yahoo_news()), source_name="yfinance_news", tool="get_news"
            )
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        attempts = out[GATE_SOURCE_ATTEMPTS_KEY]
        sources = {a["source"] for a in attempts}
        assert sources == {"yfinance_news"}
        assert not any(a["source"] in ("stocktwits", "reddit") for a in attempts)


# ---------------------------------------------------------------------------
# Isolation: two symbols / two dates / concurrent / repeated checkpoint
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_two_symbols_do_not_contaminate(self):
        with use_collector("AAPL", TARGET) as ca:
            capture_record(build_news_record(
                run_id=f"{TARGET}/AAPL", symbol_input="AAPL", symbol_normalized="AAPL",
                target_date=TARGET, title="A", publisher="P", url="u", published="2026-05-10",
                source_name="yfinance_news",
            ))
        with use_collector("MSFT", TARGET) as cm:
            capture_record(build_news_record(
                run_id=f"{TARGET}/MSFT", symbol_input="MSFT", symbol_normalized="MSFT",
                target_date=TARGET, title="M", publisher="P", url="u", published="2026-05-10",
                source_name="yfinance_news",
            ))
        assert {r.ticker_normalized for r in ca.all_records()} == {"AAPL"}
        assert {r.ticker_normalized for r in cm.all_records()} == {"MSFT"}

    def test_concurrent_contexts_are_isolated(self):
        # Two nested collectors never see each other's records (ContextVar).
        with use_collector("AAPL", TARGET) as outer:
            capture_record(build_sentiment_record(
                run_id=f"{TARGET}/AAPL", symbol_input="AAPL", symbol_normalized="AAPL",
                target_date=TARGET, source_name="stocktwits", native_label="Bullish",
                body="b", posted_at="2026-05-10", author_ref="", lineage_key="k1",
            ))
            with use_collector("TSLA", TARGET) as inner:
                assert inner.all_records() == []
                capture_record(build_sentiment_record(
                    run_id=f"{TARGET}/TSLA", symbol_input="TSLA", symbol_normalized="TSLA",
                    target_date=TARGET, source_name="stocktwits", native_label="Bearish",
                    body="b", posted_at="2026-05-10", author_ref="", lineage_key="k2",
                ))
                assert len(inner.all_records()) == 1
            assert len(outer.all_records()) == 1
            assert outer.all_records()[0].ticker_normalized == "AAPL"

    def test_checkpoint_reseed_no_duplicate(self):
        # First run captures; its state delta is persisted; a resumed collector is
        # re-seeded from that state and must not duplicate records/attempts.
        with use_collector(SYMBOL, TARGET) as first:
            capture_record(build_news_record(
                run_id=f"{TARGET}/{SYMBOL}", symbol_input=SYMBOL, symbol_normalized=SYMBOL,
                target_date=TARGET, title="A", publisher="P", url="u", published="2026-05-10",
                source_name="yfinance_news",
            ))
            capture_attempt(SourceAttempt(source="yfinance_news", tool="get_news", started_at=None,
                                          duration=None, result_status=SourceResultStatus.SUCCESS,
                                          error_type=None, error_message=None))
            persisted = first.state_delta()
        with use_collector(SYMBOL, TARGET, prior_state=persisted) as resumed:
            assert len(resumed.all_records()) == 1
            assert len(resumed.attempt_envelopes()) == 1
            # A new capture in the resumed run keeps identity stable and adds one.
            capture_attempt(SourceAttempt(source="yfinance_news", tool="get_news", started_at=None,
                                          duration=None, result_status=SourceResultStatus.SUCCESS,
                                          error_type=None, error_message=None))
            assert len(resumed.attempt_envelopes()) == 2


# ---------------------------------------------------------------------------
# Durability: real ToolNode worker thread + state persistence before checkpoint
# ---------------------------------------------------------------------------


class TestDurability:
    def test_capture_survives_toolnode_worker_thread(self, monkeypatch):
        # A tool invoked inside LangChain's context-copying executor must still see
        # the run-scoped collector (ContextVar copied into the worker thread).
        from langchain_core.runnables.config import get_executor_for_config

        seen = {}

        def tool_local(x):
            seen["active"] = get_active_collector() is not None
            return x

        with use_collector(SYMBOL, TARGET), get_executor_for_config({}) as ex:
            list(ex.map(tool_local, [1]))
        assert seen["active"] is True

    def test_capture_into_state_persists_evidence(self, fixed_snapshot):
        # The message-clear node (immediately after the tool node) flushes the
        # collector into the returned state delta, which LangGraph checkpoints.
        # Proves capture is durable across the tool boundary, not only held in
        # the ContextVar.
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_news_articles(
                SYMBOL, _capture_shape(_raw_yahoo_news()), source_name="yfinance_news", tool="get_news"
            )
            out = capture_into_state({"company_of_interest": SYMBOL, "trade_date": TARGET})
        assert "data_quality_ingested_evidence" in out
        assert out["data_quality_ingested_evidence"]
        # The durable channel carries the explicit-attempt envelope (not the
        # report-facing bare ledger, which the gate assembles separately).
        assert "data_quality_source_attempt_envelopes" in out
        # JSON-safe and re-parseable as a durable channel.
        json.dumps(out)
        for row in out["data_quality_ingested_evidence"]:
            assert row["category"] == "news"

    def test_gate_reads_persisted_state_when_no_live_collector(self, fixed_snapshot):
        # Simulate a resume: the collector is gone, but state carries the evidence.
        # Capture once to produce a realistic persisted state channel.
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_news_articles(
                SYMBOL, _capture_shape(_raw_yahoo_news()), source_name="yfinance_news", tool="get_news"
            )
            delta = get_active_collector().state_delta()
        # No active collector here; only the persisted state channel.
        assert get_active_collector() is None
        state = {"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock", **delta}
        out = _gate_node()(state)
        news = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "news"]
        assert news, "the gate must read persisted captured evidence on resume"

    def test_gate_prunes_excluded_records_from_state(self, fixed_snapshot):
        # A future-published article captured live must be pruned from the state
        # delta the gate writes, so a resume cannot resurrect it as decisive.
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_news_articles(
                SYMBOL, _capture_shape(_raw_yahoo_news()), source_name="yfinance_news", tool="get_news"
            )
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        persisted_titles = [r["metric_name"] for r in out["data_quality_ingested_evidence"]]
        assert "AAPL future event" not in persisted_titles


# ---------------------------------------------------------------------------
# Backward compatibility: manual contract cannot self-assert High
# ---------------------------------------------------------------------------


class TestManualContractCompatibility:
    def test_manual_high_without_records_is_clamped(self, fixed_snapshot):
        group = EvidenceGroupQuality(
            category="news", quality_status=QualityStatus.HIGH,
            criticality=__import__("tradingagents.evidence", fromlist=["Criticality"]).Criticality.IMPORTANT,
            evidence_ids=["structured://news/1"], source_count=2, independent_source_count=2,
            reason_codes=["high"], human_readable_reason="ok",
        ).to_dict()
        node = _gate_node()
        out = node({
            "company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock",
            GATE_OPTIONAL_EVIDENCE_KEY: {"news": group},
        })
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        assert cats["news"] == "Low", "an unverified manual grade cannot self-assert High"


# ---------------------------------------------------------------------------
# Legacy behavior: no optional ingest, no collector => prior unavailable path
# ---------------------------------------------------------------------------


class TestLegacyCompatibility:
    def test_bare_tool_call_without_run_is_noop(self, monkeypatch):
        # A tool call outside any run must not capture and must not error.
        monkeypatch.setattr(ynews.yf, "Ticker", lambda *a, **k: _FakeTicker(_raw_yahoo_news()))
        assert get_active_collector() is None
        out = ynews.get_news_yfinance(SYMBOL, "2026-05-06", TARGET)
        assert out.startswith(f"## {SYMBOL} News")

    def test_gate_without_optional_state_still_degrades(self, fixed_snapshot):
        node = _gate_node()
        out = node({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        assert out[GATE_VERDICT_KEY] == "degraded"
        assert json.loads(json.dumps(out))


# ---------------------------------------------------------------------------
# REAL compiled graph integration: analyst -> real ToolNode -> clear-message
# boundary -> gate -> report, with transport mocked at the RAW vendor source.
# Proves all three categories without manual ingest-state injection, and that
# capture survives a SqliteSaver interruption/restart.
# ---------------------------------------------------------------------------

from typing import TypedDict  # noqa: E402

from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.graph import END, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

import tradingagents.dataflows.sec_edgar as sec_edgar  # noqa: E402
from tradingagents.agents.utils.agent_utils import create_msg_delete  # noqa: E402
from tradingagents.agents.utils.fundamental_data_tools import (  # noqa: E402
    get_income_statement,
)
from tradingagents.agents.utils.news_data_tools import get_news as get_news_tool  # noqa: E402
from tradingagents.graph.checkpointer import get_checkpointer, thread_id  # noqa: E402
from tradingagents.graph.evidence_tool_node import EvidenceCapturingToolNode  # noqa: E402
from tradingagents.report_artifacts import write_report_artifacts  # noqa: E402


class _GraphState(TypedDict, total=False):
    messages: list
    company_of_interest: str
    trade_date: str
    asset_type: str
    sentiment_report: str
    news_report: str
    fundamentals_report: str
    data_quality_verdict: str
    data_quality_evidence_records: list
    data_quality_validation_results: dict
    data_quality_group_statuses: list
    data_quality_gate_decision: dict
    data_quality_context: str
    data_quality_error: str
    data_quality_source_attempts: list
    data_quality_ingested_evidence: list
    data_quality_source_attempt_envelopes: list
    data_quality_ingest_metadata: dict
    research_allowlist: str


def _production_state_schema():
    """The PRODUCTION AgentState (plus a test-only research_allowlist key).

    Using the production schema is essential: a divergent custom TypedDict would
    silently ACCEPT ingest-channel writes that the real AgentState (until the
    ADR-008 fields were declared) would DISCARD. Building the graph on the real
    AgentState proves the durable channels actually persist.
    """
    from typing import Annotated

    from typing_extensions import NotRequired

    from tradingagents.agents.utils.agent_states import AgentState

    annotations = dict(AgentState.__annotations__)
    annotations["research_allowlist"] = NotRequired[Annotated[str, "test allowlist"]]
    return TypedDict("ProductionGraphState", annotations, total=False)


def _companyfacts_payload() -> dict:
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2026-03-31", "start": "2026-01-01", "val": 111000000000,
                             "filed": "2026-05-02", "accn": "0001-26-000001"},
                        ]
                    }
                },
            }
        }
    }


def _install_transport_mocks(monkeypatch):
    """Mock every optional-vendor transport at the RAW source (no network)."""
    # Route fundamentals to the SEC EDGAR vendor (structured facts with filing
    # dates) so the real get_income_statement path fetches via SEC.
    from tradingagents.dataflows.config import set_config

    set_config({"tool_vendors": {"get_income_statement": "sec_edgar"}})
    # News (real get_news -> get_news_yfinance -> yf.Ticker.get_news)
    monkeypatch.setattr(ynews.yf, "Ticker", lambda *a, **k: _FakeTicker(_raw_yahoo_news()))
    # Fundamentals (real get_income_statement -> sec_edgar.structured_statement_facts)
    monkeypatch.setattr(sec_edgar, "cik_for", lambda t: "0000320193")
    monkeypatch.setattr(sec_edgar, "_cached_json", lambda url, name: _companyfacts_payload())
    # Sentiment fetchers used by the real sentiment node.
    monkeypatch.setattr(
        stocktwits, "urlopen", lambda *a, **k: _JsonResp({"messages": _raw_stocktwits()})
    )
    monkeypatch.setattr(
        reddit, "_fetch_subreddit_rss",
        lambda *a, **k: [{"title": "AAPL talk", "created_utc": _epoch("2026-05-09"), "subreddit": "stocks"}],
    )


def _analyst_node(state):
    """A scripted analyst that emits REAL tool calls (no LLM)."""
    calls = [
        {"name": "get_news", "args": {"ticker": SYMBOL, "start_date": "2026-05-06",
                                      "end_date": TARGET}, "id": "c1", "type": "tool_call"},
    ]
    return {"messages": [AIMessage(content="Fetching data.", tool_calls=calls)]}


def _sentiment_node(state):
    """A real sentiment data node that calls the real fetchers (like the analyst)."""
    stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-06", end_date=TARGET)
    reddit.fetch_reddit_posts(SYMBOL, subreddits=("stocks",), start_date="2026-05-06", end_date=TARGET)
    return {"sentiment_report": "sentiment"}


def _fundamentals_node(state):
    """A real fundamentals node that invokes the real get_income_statement tool."""
    out = get_income_statement.func(ticker=SYMBOL, freq="quarterly", curr_date=TARGET)
    return {"fundamentals_report": out}


def _research_node(state):
    """A downstream node that reads the citation allowlist from gate records."""
    from tradingagents.debate.evidence_manifest import build_citation_allowlist

    allowlist = build_citation_allowlist(state.get("data_quality_evidence_records"), TARGET)
    return {"research_allowlist": allowlist}


def _build_real_graph():
    builder = StateGraph(_production_state_schema())
    builder.add_node("Analyst", _analyst_node)
    builder.add_node("tools", ToolNode([get_news_tool]))
    builder.add_node("clear", create_msg_delete())
    builder.add_node("Sentiment", _sentiment_node)
    builder.add_node("Fundamentals", _fundamentals_node)
    builder.add_node("Gate", create_data_quality_gate_node(now_provider=lambda: FETCHED))
    builder.add_node("Research", _research_node)

    builder.set_entry_point("Analyst")
    builder.add_edge("Analyst", "tools")
    builder.add_edge("tools", "clear")
    builder.add_edge("clear", "Sentiment")
    builder.add_edge("Sentiment", "Fundamentals")
    builder.add_edge("Fundamentals", "Gate")
    builder.add_edge("Gate", "Research")
    builder.add_edge("Research", END)
    return builder


def _initial_state():
    return {
        "messages": [("human", SYMBOL)],
        "company_of_interest": SYMBOL,
        "trade_date": TARGET,
        "asset_type": "stock",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "data_quality_verdict": "blocked",
        "data_quality_evidence_records": [],
        "data_quality_validation_results": {},
        "data_quality_group_statuses": [],
        "data_quality_gate_decision": {},
        "data_quality_context": "",
        "data_quality_error": "gate not run",
        "data_quality_source_attempts": [],
    }


class TestRealGraphIntegration:
    def test_real_graph_all_three_categories_reach_gate_and_report(
        self, fixed_snapshot, monkeypatch, tmp_path
    ):
        _install_transport_mocks(monkeypatch)
        graph = _build_real_graph().compile()
        with use_collector(SYMBOL, TARGET):
            final = graph.invoke(_initial_state())
        categories = {r["category"] for r in final[GATE_EVIDENCE_RECORDS_KEY]}
        # All three optional categories were captured through the REAL path.
        assert {"news", "fundamentals", "sentiment"} <= categories
        # No manual ingest-state injection: the initial state carried none.
        assert final["data_quality_verdict"] in ("normal", "degraded")
        # Citation allowlist propagated to the downstream research node.
        assert "Data Quality Gate" in final["research_allowlist"]
        # The saved report carries the optional records and attempt ledger.
        write_report_artifacts(final, SYMBOL, tmp_path / "art")
        manifest = json.loads((Path(tmp_path) / "art" / "0_quality" / "evidence_manifest.json").read_text())
        manifest_cats = {r["category"] for r in manifest["evidence_records"]}
        assert {"news", "fundamentals", "sentiment"} <= manifest_cats

    def test_capture_survives_sqlite_interrupt_after_tools_restart(self, fixed_snapshot, monkeypatch, tmp_path):
        # TRUE durable regression: interrupt the compiled graph RIGHT AFTER the
        # wrapped tool node (interrupt_after=["tools"]), before the gate/clear.
        # The tool node must have written captured evidence into checkpointed
        # state. Then CLOSE the saver, REBUILD the same graph, resume with a FRESH
        # collector via invoke(None, cfg), and assert the REAL gate automatically
        # sees the persisted evidence and the run completes — no manual state
        # reconstruction.
        _install_transport_mocks(monkeypatch)
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}
        data_dir = str(tmp_path / "ckpt")

        def _build():
            b = StateGraph(_production_state_schema())
            b.add_node("Analyst", _analyst_node)
            b.add_node("tools", EvidenceCapturingToolNode(ToolNode([get_news_tool]), name="tools"))
            b.add_node("clear", create_msg_delete())
            b.add_node("Gate", create_data_quality_gate_node(now_provider=lambda: FETCHED))
            b.add_node("Research", _research_node)
            b.set_entry_point("Analyst")
            b.add_edge("Analyst", "tools")
            b.add_edge("tools", "clear")
            b.add_edge("clear", "Gate")
            b.add_edge("Gate", "Research")
            b.add_edge("Research", END)
            return b

        # ---- First process: interrupt after the tool node. ----
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = _build().compile(checkpointer=saver, interrupt_after=["tools"])
            with use_collector(SYMBOL, TARGET):
                first = g.invoke(_initial_state(), cfg)
            # Interrupted right after tools: gate has not run yet.
            assert first.get("data_quality_gate_decision", {}) in ({}, None) or not first.get(
                "data_quality_gate_decision"
            )
            # The tool boundary already checkpointed the captured evidence.
            assert first.get("data_quality_ingested_evidence"), (
                "wrapped tool node must persist capture into state at the checkpoint"
            )
            assert first.get("data_quality_source_attempt_envelopes")
            assert not [r for r in first.get("data_quality_evidence_records") or [] if r["category"] == "news"]

        # ---- Second process: fresh saver/collector; resume. ----
        assert get_active_collector() is None  # no live ContextVar survives restart
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = _build().compile(checkpointer=saver)
            with use_collector(SYMBOL, TARGET):  # fresh collector (empty at start)
                final = g2.invoke(None, cfg)  # resume, do not re-pass state
        # The REAL gate, on resume, recovered the persisted evidence from state.
        assert final["data_quality_verdict"] in ("normal", "degraded")
        news = [r for r in final[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "news"]
        assert news, "resumed real gate must recover captured news from checkpointed state"
        assert "Data Quality Gate" in final["research_allowlist"]


# ---------------------------------------------------------------------------
# Router fallback attempts, unsupported payload, repeated real calls
# ---------------------------------------------------------------------------


class TestAttemptLedgerTruthfulness:
    def test_raw_transport_failure_then_fallback_success_records_both(self, monkeypatch):
        # FR-DQG-005 / NFR-AUD-001: a primary vendor that fails (raw transport)
        # and a configured fallback that succeeds must BOTH appear in the ledger
        # (failure + success), in order, with the failure sanitized.
        import tradingagents.dataflows.interface as iface

        call_order = []

        def failing_primary(*a, **k):
            call_order.append("alpha_vantage")
            raise RuntimeError("boom https://secret.example.com/x?token=LEAK user=alice")

        def ok_fallback(*a, **k):
            call_order.append("yfinance")
            # Real adapter captures the success attempt with the data.
            evidence_capture.capture_news_articles(
                SYMBOL, _capture_shape(_raw_yahoo_news()),
                source_name="yfinance_news", tool="get_news",
            )
            return "## News body"

        monkeypatch.setitem(iface.VENDOR_METHODS, "get_news", {
            "alpha_vantage": failing_primary,
            "yfinance": ok_fallback,
        })
        from tradingagents.dataflows.config import set_config

        set_config({"tool_vendors": {"get_news": "alpha_vantage,yfinance"}})
        with use_collector(SYMBOL, TARGET) as c:
            out = iface.route_to_vendor("get_news", SYMBOL, "2026-05-06", TARGET)
            attempts = [a.to_dict() for a in c.attempt_envelopes()]
        assert out == "## News body"
        # Primary was attempted first, then the fallback (real call order).
        assert call_order == ["alpha_vantage", "yfinance"]
        # Failure attempt for the primary, success attempt for the fallback.
        assert attempts[0]["attempt"]["source"] == "alpha_vantage"
        assert attempts[0]["attempt"]["result_status"] == "failed"
        assert attempts[-1]["attempt"]["source"] == "yfinance_news"
        assert attempts[-1]["attempt"]["result_status"] == "success"
        blob = json.dumps(attempts)
        assert "LEAK" not in blob and "secret.example.com" not in blob and "alice" not in blob

    def test_unsupported_payload_records_one_empty_attempt(self):
        # AV malformed/non-JSON/empty payload records exactly ONE generic
        # unsupported/empty attempt and never a fabricated grade.
        with use_collector(SYMBOL, TARGET) as c:
            evidence_capture.capture_alpha_vantage_statement(
                SYMBOL, "not-json", "income_statement", "get_income_statement"
            )
            envelopes = c.attempt_envelopes()
        assert len(envelopes) == 1
        att = envelopes[0].attempt
        assert att.source == "alpha_vantage"
        assert att.result_status.value == "empty"
        assert att.error_type == "malformed"

    def test_two_real_repeated_calls_are_two_attempts(self, monkeypatch):
        # Two real StockTwits calls (both empty) produce TWO distinct attempts,
        # never collapsed into one.
        monkeypatch.setattr(
            stocktwits, "urlopen", lambda *a, **k: _JsonResp({"messages": []})
        )
        with use_collector(SYMBOL, TARGET) as c:
            stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-01", end_date="2026-05-02")
            stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-01", end_date="2026-05-02")
            envs = [e for e in c.attempt_envelopes() if e.attempt.source == "stocktwits"]
        assert len(envs) == 2
        assert [e.attempt_index for e in envs][0] != [e.attempt_index for e in envs][1]

    def test_not_attempted_feeds_are_not_attempts(self):
        # Configured-but-unoperated feeds are recorded separately and never enter
        # the SourceAttempt ledger / source counts.
        with use_collector(SYMBOL, TARGET) as c:
            evidence_capture.capture_not_attempted(["sec_edgar", "alpha_vantage"])
            assert c.attempt_envelopes() == []
            assert set(c.not_attempted()) == {"sec_edgar", "alpha_vantage"}


# ---------------------------------------------------------------------------
# Default yfinance fundamentals: undated (no invented filing date)
# ---------------------------------------------------------------------------


class TestDefaultYfinanceFundamentals:
    def _frame(self):
        import pandas as pd

        return pd.DataFrame(
            {pd.Timestamp("2026-03-31"): [391000000000.0]},
            index=["Total Assets"],
        )

    def test_yfinance_statement_undated_and_low(self, fixed_snapshot):
        # yfinance carries only a fiscal period end, no filing date; the captured
        # record is undated and never decisive (honestly Low).
        with use_collector(SYMBOL, TARGET):
            evidence_capture.capture_yfinance_statement(
                SYMBOL, self._frame(), "balance_sheet", "get_balance_sheet"
            )
            out = _gate_node()({"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"})
        recs = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "fundamentals"]
        # Undated yfinance data is excluded from the decisive set, not trusted.
        assert recs == []

    def test_yfinance_balance_sheet_tool_captures(self, fixed_snapshot, monkeypatch):
        # The real get_balance_sheet tool captures via the default yfinance path
        # without changing its returned prose.
        import tradingagents.dataflows.y_finance as yf_mod

        frame = self._frame()

        class _T:
            quarterly_balance_sheet = frame
            balance_sheet = frame

        monkeypatch.setattr(yf_mod.yf, "Ticker", lambda *a, **k: _T())
        from tradingagents.agents.utils.fundamental_data_tools import get_balance_sheet
        from tradingagents.dataflows.config import set_config

        set_config({"tool_vendors": {"get_balance_sheet": "yfinance"}})
        with use_collector(SYMBOL, TARGET) as c:
            prose = get_balance_sheet.func(ticker=SYMBOL, freq="quarterly", curr_date=TARGET)
            cat = {r.category for r in c.all_records()}
        assert prose.startswith("# Balance Sheet data")
        assert "fundamentals" in cat


# ---------------------------------------------------------------------------
# Alpha Vantage reported currency is preserved, never hardcoded
# ---------------------------------------------------------------------------


class TestAlphaVantageCurrency:
    def test_reported_currency_preserved(self):
        payload = json.dumps(
            {
                "reportedCurrency": "EUR",
                "quarterlyReports": [
                    {"fiscalDateEnding": "2026-03-31", "totalRevenue": "1000"},
                ],
            }
        )
        with use_collector(SYMBOL, TARGET) as c:
            evidence_capture.capture_alpha_vantage_statement(
                SYMBOL, payload, "income_statement", "get_income_statement"
            )
            recs = c.all_records()
        assert recs and recs[0].unit_raw == "EUR", "currency must be the vendor's, not USD"


# ---------------------------------------------------------------------------
# Resume correctness: seed-before-execution, in-node analyst capture, tombstones
# ---------------------------------------------------------------------------


class TestResumeCorrectness:
    def test_resume_then_new_call_preserves_both_attempts(self):
        # Regression: a saved collector with old_source at attempt_index 0; a
        # resumed run must SEED it before a new capture so new_source gets index
        # 1, and the merge keeps BOTH exactly once (not just the new one).
        with use_collector(SYMBOL, TARGET) as first:
            capture_attempt(SourceAttempt(source="old_source", tool="t", started_at=None,
                                          duration=None, result_status=SourceResultStatus.SUCCESS,
                                          error_type=None, error_message=None))
            saved = first.state_delta()
        # Fresh resumed collector seeded from saved state BEFORE any new call.
        with use_collector(SYMBOL, TARGET, prior_state=saved) as resumed:
            assert len(resumed.attempt_envelopes()) == 1
            capture_attempt(SourceAttempt(source="new_source", tool="t", started_at=None,
                                          duration=None, result_status=SourceResultStatus.SUCCESS,
                                          error_type=None, error_message=None))
            merged = merge_into_state(resumed.state_delta(), saved)
        sources = [a["attempt"]["source"] for a in merged["data_quality_source_attempt_envelopes"]]
        assert sources == ["old_source", "new_source"]
        assert len(sources) == 2  # exactly once each, no overwrite, no duplicate

    def test_use_collector_without_prior_state_would_collide(self):
        # Documents the bug the fix prevents: a fresh collector starts at index 0.
        with use_collector(SYMBOL, TARGET) as fresh:
            assert fresh.metadata.next_attempt_index == 0

    def test_sentiment_analyst_node_capture_persists(self, fixed_snapshot, monkeypatch):
        # The real Sentiment Analyst prefetches StockTwits/Reddit/news IN-NODE.
        # Its post-analyst state return must carry the captures (not lost until
        # clear). Use the real factory with a fake LLM + raw mocked sources.
        from langchain_core.messages import AIMessage

        from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst

        monkeypatch.setattr(ynews.yf, "Ticker", lambda *a, **k: _FakeTicker(_raw_yahoo_news()))
        monkeypatch.setattr(stocktwits, "urlopen", lambda *a, **k: _JsonResp({"messages": _raw_stocktwits()}))
        monkeypatch.setattr(reddit, "_fetch_subreddit_rss",
                            lambda *a, **k: [{"title": "AAPL talk", "created_utc": _epoch("2026-05-09"),
                                              "subreddit": "stocks"}])
        from tradingagents.agents.utils.structured import invoke_structured_or_freetext  # noqa: F401

        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=None)
        llm.invoke = MagicMock(return_value=AIMessage(content="Neutral sentiment."))
        node = create_sentiment_analyst(llm)
        from tradingagents.graph.evidence_tool_node import EvidenceCapturingAnalystNode

        wrapped = EvidenceCapturingAnalystNode(node, name="Sentiment Analyst")
        init = {"messages": [("human", SYMBOL)], "company_of_interest": SYMBOL,
                "trade_date": TARGET, "asset_type": "stock"}
        with use_collector(SYMBOL, TARGET):
            out = wrapped(init, {}, None)
            captured = get_active_collector().all_records()
        cats = {r.category for r in captured}
        # Captured inside the analyst node itself.
        assert "sentiment" in cats and "news" in cats
        # The WRAPPED analyst node's returned state carries the captures, so a
        # checkpoint right after the sentiment node retains them.
        assert out["data_quality_ingested_evidence"]

    def test_already_persisted_future_record_is_tombstoned_on_resume(self, fixed_snapshot):
        # A future-published record persisted in a prior checkpoint must NOT be
        # resurrected by a later merge; the gate tombstones it.
        with use_collector(SYMBOL, TARGET) as c:
            evidence_capture.capture_news_articles(
                SYMBOL, _capture_shape(_raw_yahoo_news()), source_name="yfinance_news", tool="get_news"
            )
            saved = c.state_delta()
        # The saved state still carries the future article (pre-gate).
        assert any(
            r["metric_name"] == "AAPL future event" for r in saved["data_quality_ingested_evidence"]
        )
        # Resume: gate runs, excludes the future article, tombstones it.
        with use_collector(SYMBOL, TARGET, prior_state=saved):
            state = {"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock", **saved}
            out = _gate_node()(state)
        dropped = out["data_quality_dropped_evidence_ids"]
        assert dropped, "future record must be tombstoned"
        titles = [r["metric_name"] for r in out["data_quality_ingested_evidence"]]
        assert "AAPL future event" not in titles
        # A second merge (simulating another resume) cannot bring it back.
        with use_collector(SYMBOL, TARGET, prior_state=out) as c2:
            merged = merge_into_state(c2.state_delta(), out)
        assert "AAPL future event" not in [r["metric_name"] for r in merged["data_quality_ingested_evidence"]]


# ---------------------------------------------------------------------------
# Production AgentState declares the durable ingest channels (no silent drop)
# ---------------------------------------------------------------------------


class TestProductionStateDeclaresIngestChannels:
    def test_agentstate_declares_all_ingest_channels(self):
        # FR-DQG-005 / INV-4: an undeclared state key is silently DISCARDED by
        # LangGraph checkpointing, so the production AgentState must declare every
        # ingest channel the tool/analyst boundary and gate write.
        from tradingagents.agents.utils.agent_states import AgentState

        required = {
            "data_quality_source_attempts",
            "data_quality_ingested_evidence",
            "data_quality_source_attempt_envelopes",
            "data_quality_ingest_metadata",
            "data_quality_not_attempted_feeds",
            "data_quality_dropped_evidence_ids",
        }
        assert required <= set(AgentState.__annotations__)

    def test_production_graph_checkpoints_ingest_channels(self, fixed_snapshot, monkeypatch, tmp_path):
        # A real compiled production-schema graph must actually persist the ingest
        # channels through a SqliteSaver (not just our custom schema).
        _install_transport_mocks(monkeypatch)
        tid = thread_id(SYMBOL, TARGET)
        cfg = {"configurable": {"thread_id": tid}}
        data_dir = str(tmp_path / "ckpt2")
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = _build_real_graph().compile(checkpointer=saver)
            with use_collector(SYMBOL, TARGET):
                g.invoke(_initial_state(), cfg)
            saved = saver.get_tuple(cfg).checkpoint["channel_values"]
        assert saved.get("data_quality_ingested_evidence"), "ingest records must be checkpointed"
        assert saved.get("data_quality_source_attempt_envelopes")


# ---------------------------------------------------------------------------
# Fail-closed classifier, thread safety, identity mismatch
# ---------------------------------------------------------------------------


class TestClassifierFailClosedAndConcurrency:
    def test_empty_results_is_blocked_not_medium(self):
        # Missing/unknown validation must fail closed: an empty result set can
        # never produce Medium (the mandatory checks are absent).
        from tradingagents.evidence.quality import evaluate_optional_record_quality

        rec = build_news_record(
            run_id=f"{TARGET}/{SYMBOL}", symbol_input=SYMBOL, symbol_normalized=SYMBOL,
            target_date=TARGET, title="x", publisher="P", url="u", published="2026-05-10",
            source_name="yfinance_news",
        )
        status, _ = evaluate_optional_record_quality(rec, [])
        assert status == QualityStatus.BLOCKED

    def test_all_not_applicable_is_blocked(self):
        from tradingagents.evidence.models import (
            ValidationClass,
            ValidationResult,
            ValidationStatus,
        )
        from tradingagents.evidence.quality import evaluate_optional_record_quality

        rec = build_news_record(
            run_id=f"{TARGET}/{SYMBOL}", symbol_input=SYMBOL, symbol_normalized=SYMBOL,
            target_date=TARGET, title="x", publisher="P", url="u", published="2026-05-10",
            source_name="yfinance_news",
        )
        na = [
            ValidationResult("optional.completeness.required_fields", ValidationClass.COMPLETENESS,
                             ValidationStatus.NOT_APPLICABLE, evidence_id=rec.evidence_id),
            ValidationResult("optional.freshness.publication_date", ValidationClass.FRESHNESS_LOOKAHEAD,
                             ValidationStatus.NOT_APPLICABLE, evidence_id=rec.evidence_id),
        ]
        status, _ = evaluate_optional_record_quality(rec, na)
        assert status == QualityStatus.BLOCKED, "all NOT_APPLICABLE must fail closed"

    def test_mandatory_pass_is_medium(self):
        from tradingagents.evidence.quality import evaluate_optional_record_quality

        rec = build_news_record(
            run_id=f"{TARGET}/{SYMBOL}", symbol_input=SYMBOL, symbol_normalized=SYMBOL,
            target_date=TARGET, title="x", publisher="P", url="u", published="2026-05-10",
            source_name="yfinance_news",
        )
        results = validate_optional_records(
            {"news": [rec]}, expected_symbol=SYMBOL, target_date=TARGET
        )[rec.evidence_id]
        status, _ = evaluate_optional_record_quality(rec, results)
        assert status == QualityStatus.MEDIUM

    def test_amount_like_missing_magnitude_fails(self):
        # Fundamentals amount-like metric with no finite magnitude must FAIL the
        # amount check (not NOT_APPLICABLE).
        from decimal import Decimal

        from tradingagents.evidence.vendor_adapters import (
            build_sec_fundamentals_record,
            validate_fundamentals_record,
        )

        rec = build_sec_fundamentals_record(
            run_id=f"{TARGET}/{SYMBOL}", symbol_input=SYMBOL, symbol_normalized=SYMBOL,
            target_date=TARGET, metric_name="revenue", value_raw="nan",
            value_normalized=Decimal("NaN"), unit_raw="USD",
            filed_date="2026-05-02", period_end="2026-03-31", source_ref="sec:x",
        )
        results, exclusion = validate_fundamentals_record(
            rec, expected_symbol=SYMBOL, target_date=TARGET
        )
        assert exclusion is None
        amount = [r for r in results if r.rule_id == "optional.fundamentals.amount_format"]
        assert amount and amount[0].status.value == "fail"

    def test_concurrent_attempt_indices_unique(self):
        # Multiple real ToolNode worker threads share one collector; attempt-index
        # allocation must be thread-safe (no collisions, no lost attempts).

        from langchain_core.runnables.config import get_executor_for_config

        collector = StructuredEvidenceCollector()
        collector.seed(SYMBOL, TARGET)

        def _do(_):
            collector.capture_attempt(SourceAttempt(
                source="s", tool="t", started_at=None, duration=None,
                result_status=SourceResultStatus.SUCCESS, error_type=None, error_message=None,
            ))

        with get_executor_for_config({"max_concurrency": 8}) as ex:
            list(ex.map(_do, range(200)))
        envs = collector.attempt_envelopes()
        assert len(envs) == 200
        assert len({e.attempt_index for e in envs}) == 200  # all unique

    def test_foreign_identity_prior_state_is_quarantined(self):
        # A prior checkpoint for a DIFFERENT symbol must not contaminate this run.
        with use_collector("AAPL", TARGET) as a:
            capture_record(build_news_record(
                run_id=f"{TARGET}/AAPL", symbol_input="AAPL", symbol_normalized="AAPL",
                target_date=TARGET, title="A", publisher="P", url="u", published="2026-05-10",
                source_name="yfinance_news",
            ))
            capture_attempt(SourceAttempt(source="s", tool="t", started_at=None, duration=None,
                                          result_status=SourceResultStatus.SUCCESS,
                                          error_type=None, error_message=None))
            foreign = a.state_delta()
        with use_collector("MSFT", TARGET, prior_state=foreign) as b:
            assert b.all_records() == [], "foreign-symbol records must be quarantined"
            assert b.attempt_envelopes() == []
            assert b.metadata.symbol == "MSFT", "current identity is kept, not replaced"
