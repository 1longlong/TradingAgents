"""Python 3.10 CI repair: cross-version normalization of a terminal UTC ``Z``.

Requirement/invariant traceability: FR-DQG-004 (multi-category gate optional
evidence ingestion, sentiment path), NFR-PIT-001 (point-in-time integrity: a
future terminal-``Z`` source date is rejected as look-ahead), NFR-DET-001
(deterministic date parsing), INV-2 (determinism), INV-3 (no look-ahead), and
NFR-OFF-001 (offline, zero forbidden socket attempts).

Context: ``datetime.fromisoformat`` only accepts a terminal uppercase ``Z`` from
Python 3.11 onward. On Python 3.10 a legitimate vendor timestamp such as
``2026-05-10T12:00:00Z`` therefore parsed to ``None`` inside
``tradingagents.evidence.policy.to_date``, which dropped the StockTwits
sentiment records and made the sentiment category ``Blocked`` on CI.

The repair normalizes **only** the terminal uppercase ``Z`` of a legitimate
extended date+time-shaped string to ``+00:00`` before parsing. The guard is a
date+time-shape test (extended ``YYYY-MM-DD``, exactly one separator character,
then a time payload), so it recognizes ``T``, a space, and the ``Z`` used as the
one-character ``fromisoformat`` separator alike. It preserves:

- the legacy ``to_date`` numeric/compact/separator acceptance outside the
  terminal-``Z`` repair (e.g. ``20260510`` still parses; recorded honestly);
- rejection of a date-only ``Z`` (``2026-05-10Z``), malformed dates/times, a
  repeated ``Z`` suffix, and a lowercase ``z``;
- calendar-date (not UTC date-shifting) semantics for other offsets.

The deterministic "pre-3.11" simulation below restricts **only**
``policy.datetime.fromisoformat`` to reject a terminal uppercase ``Z`` and is
explicitly a simulated parser restriction, NOT an actual Python 3.10 run. No
Python 3.10 runtime is installed here; the actual remote 3.10 CI remains pending.

All tests are socket-disabled offline with mocked vendors/models.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

import tradingagents.dataflows.market_data_validator as validator
import tradingagents.evidence.policy as policy
from tradingagents.dataflows import stocktwits
from tradingagents.evidence.ingest import use_collector
from tradingagents.evidence.vendor_adapters import (
    _iso_date,
    build_sentiment_record,
    validate_sentiment_record,
)
from tradingagents.graph.data_quality_gate import (
    GATE_EVIDENCE_RECORDS_KEY,
    create_data_quality_gate_node,
)

SYMBOL = "AAPL"
TARGET = "2026-05-13"
FETCHED = "2026-05-13T12:00:00Z"


# ---------------------------------------------------------------------------
# Deterministic pre-3.11 simulation (NOT an actual Python 3.10 run).
# ---------------------------------------------------------------------------


class _Pre311DateTime(datetime):
    """``datetime`` whose ``fromisoformat`` rejects a terminal uppercase ``Z``.

    This mirrors the pre-3.11 parser restriction used to explain the CI failure,
    without pretending to be a real Python 3.10 interpreter. Installed only on
    ``policy.datetime`` for the duration of a test.
    """

    @classmethod
    def fromisoformat(cls, text):  # type: ignore[override]
        if isinstance(text, str) and text.endswith("Z"):
            raise ValueError(f"Invalid isoformat string: {text!r}")
        return datetime.fromisoformat(text)


@pytest.fixture
def pre311_parser(monkeypatch):
    monkeypatch.setattr(policy, "datetime", _Pre311DateTime)


# ---------------------------------------------------------------------------
# to_date parsing contract (positive equivalence + preserved rejection)
# ---------------------------------------------------------------------------


class TestToDateTerminalZ:
    def test_terminal_z_equals_offset_and_calendar_date(self):
        # Positive: a terminal uppercase Z is the same instant/date as +00:00.
        expected = date(2026, 5, 10)
        assert policy.to_date("2026-05-10T12:00:00Z") == expected
        assert policy.to_date("2026-05-10T12:00:00+00:00") == expected
        assert (
            policy.to_date("2026-05-10T12:00:00Z")
            == policy.to_date("2026-05-10T12:00:00+00:00")
            == expected
        )

    def test_separator_variants_all_normalized(self):
        # Date+time-shape recognition is independent of the one separator character.
        expected = date(2026, 5, 10)
        assert policy.to_date("2026-05-10T12:00:00Z") == expected
        assert policy.to_date("2026-05-10 12:00:00Z") == expected
        # Z used as the single datetime separator (fromisoformat-supported) with a
        # terminal Z: the separator Z is preserved, the terminal Z normalized.
        assert policy.to_date("2026-05-10Z12:00:00Z") == expected

    @pytest.mark.parametrize(
        "value",
        [
            "2026-05-10T12Z",  # HH-only (at-least-HH minimum)
            "2026-05-10T12:30Z",  # HH:MM
            "2026-05-10T12:30:45Z",  # HH:MM:SS
            "2026-05-10T12:30:45.123456Z",  # fraction
            "2026-05-10 12Z",  # space separator, HH-only
            "2026-05-10Z12Z",  # Z separator, HH-only
        ],
    )
    def test_time_granularity_variants_all_normalized(self, value):
        # At least an hour component (HH) must normalize; this is the approved
        # at-least-HH guard (older native fromisoformat accepts these once the
        # terminal Z is normalized).
        assert policy._normalize_terminal_utc_z(value) != value
        assert policy._normalize_terminal_utc_z(value).endswith("+00:00")
        assert policy.to_date(value) == date(2026, 5, 10)

    def test_date_and_datetime_and_offset_inputs_unchanged(self):
        expected = date(2026, 5, 10)
        assert policy.to_date("2026-05-10") == expected
        assert policy.to_date("2026-05-10T12:00:00") == expected
        assert policy.to_date("2026-05-10T12:00:00+05:00") == expected  # calendar date kept
        assert policy.to_date(date(2026, 5, 10)) == expected
        assert policy.to_date(datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "2026-05-10Z",  # date-only Z: not date+time-shaped -> rejected
            "2026-05-10T12:00:00ZZ",  # repeated suffix Z -> rejected
            "2026-05-10T12:00:00Zz",  # terminal Z then trailing z -> rejected
            "2026-05-10T12:00:00+00:00Z",  # offset before terminal Z -> not rewritten
            "2026-05-10T12:00:00z",  # lowercase z -> rejected
            "not-a-date",
            "",
            None,
        ],
    )
    def test_invalid_and_malformed_remain_rejected(self, value):
        # Negative: the terminal-Z repair does not broaden accepted grammar.
        assert policy.to_date(value) is None

    @pytest.mark.parametrize(
        "value",
        [
            "2026-05-10T12:00:00zZ",
            "20260510",
            "20260510T120000",
        ],
    )
    def test_non_z_forms_match_native_parser_parity(self, value):
        # These non-terminal-uppercase-Z forms are interpreter-dependent (e.g.
        # compact dates and `...zZ` are accepted by 3.11+ but rejected by 3.9).
        # The guard must leave them untouched, so to_date must equal the running
        # interpreter's unpatched native parse — including None on native rejection.
        assert policy._normalize_terminal_utc_z(value) == value
        try:
            expected = datetime.fromisoformat(value).date()
        except ValueError:
            expected = None
        assert policy.to_date(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "2026-05-10T12:00:00ZZ",
            "2026-05-10T12:00:00Zz",
            "2026-05-10T12:00:00+00:00Z",
            "2026-05-10T12:00:00ZZZ",
        ],
    )
    def test_malformed_suffix_not_rewritten_at_helper_boundary(self, value):
        # Guard regression: a repeated/lowercase Z suffix or a pre-existing offset
        # before the terminal Z must NOT be rewritten. Rewriting would turn an
        # interpreter-rejected raw string into an accepted one (e.g. 3.9 accepts
        # '...+00:00' but rejects the doubled suffix), introducing acceptance.
        assert policy._normalize_terminal_utc_z(value) == value
        # And these are invalid on every interpreter (double suffix / trailing z /
        # doubled offset), so the raw text stays rejected end to end.
        assert policy.to_date(value) is None

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-05-10T12:00:00Z", "2026-05-10T12:00:00+00:00"),
            ("2026-05-10 12:00:00Z", "2026-05-10 12:00:00+00:00"),
            ("2026-05-10Z12:00:00Z", "2026-05-10Z12:00:00+00:00"),
        ],
    )
    def test_legitimate_terminal_z_rewritten_at_helper_boundary(self, value, expected):
        # Positive counterpart: only a legitimate date+time `...digit Z` is rewritten.
        assert policy._normalize_terminal_utc_z(value) == expected

    @pytest.mark.parametrize("value", [20260510, "20260510"])
    def test_legacy_numeric_and_compact_semantics_preserved(self, value):
        # Honest record: the narrow terminal-Z repair does NOT change non-Z
        # numeric/compact behavior. Whether ``fromisoformat`` accepts a compact
        # ``YYYYMMDD`` form is interpreter-dependent (3.10 rejects it; newer
        # versions accept it), so assert PARITY with the running interpreter's
        # unpatched native parser rather than forcing 3.11+ acceptance onto 3.10.
        # A native rejection must yield ``None`` (no grammar expansion; no skip).
        try:
            expected = datetime.fromisoformat(str(value).strip()).date()
        except ValueError:
            expected = None
        assert policy.to_date(value) == expected
        # Universal: boolean is never a date on any interpreter.
        assert policy.to_date(True) is None

    @pytest.mark.usefixtures("pre311_parser")
    def test_pre311_simulation_still_parses_terminal_z(self):
        # Under the simulated pre-3.11 parser restriction (which rejects a bare
        # terminal Z), to_date's own normalization still yields the correct date,
        # including the HH-only and HH:MM at-least-HH shapes.
        assert policy.to_date("2026-05-10T12:00:00Z") == date(2026, 5, 10)
        assert policy.to_date("2026-05-10Z12:00:00Z") == date(2026, 5, 10)
        assert policy.to_date("2026-05-10T12Z") == date(2026, 5, 10)  # HH-only
        assert policy.to_date("2026-05-10T12:30Z") == date(2026, 5, 10)  # HH:MM


class TestIsoDateAdapterBoundary:
    """Numeric/bool rejection is the adapter (_iso_date) contract, not to_date's."""

    @pytest.mark.parametrize("value", [20260510, True, "not-a-date", None])
    def test_iso_date_rejects_numeric_bool_malformed(self, value):
        assert _iso_date(value) is None

    def test_iso_date_terminal_z(self):
        assert _iso_date("2026-05-10T12:00:00Z") == "2026-05-10"


# ---------------------------------------------------------------------------
# Real mocked StockTwits fetch -> capture -> gate (the two CI-failed paths)
# ---------------------------------------------------------------------------


class _JsonResp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self):
        return self._body


def _raw_stocktwits(created_at=None):
    return [
        {
            "created_at": created_at or "2026-05-10T12:00:00Z",
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


@pytest.fixture
def fixed_snapshot(monkeypatch):
    import pandas as pd

    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    frame = pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )
    monkeypatch.setattr(validator, "load_ohlcv", lambda s, d, fill_gaps=True: frame)


def _gate_node():
    return create_data_quality_gate_node(now_provider=lambda: FETCHED)


def _capture_stocktwits(monkeypatch, messages):
    monkeypatch.setattr(stocktwits, "urlopen", lambda *a, **k: _JsonResp({"messages": messages}))


class TestStockTwitsToGate:
    @pytest.mark.usefixtures("pre311_parser", "fixed_snapshot")
    def test_sentiment_ingested_under_pre311_parser(self, monkeypatch):
        # Reproduces the original failing assertion 317: records is non-empty and
        # native labels survive, under the simulated pre-3.11 parser restriction.
        _capture_stocktwits(monkeypatch, _raw_stocktwits())
        with use_collector(SYMBOL, TARGET):
            stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-06", end_date=TARGET)
            out = _gate_node()(
                {"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"}
            )
        records = [r for r in out[GATE_EVIDENCE_RECORDS_KEY] if r["category"] == "sentiment"]
        assert records
        labels = {r["value_raw"] for r in records}
        assert "bullish" in labels  # native StockTwits label preserved
        assert "unlabeled" in labels  # no invented label
        blob = json.dumps(records)
        assert "secret_user" not in blob and "another_user" not in blob
        assert "to the moon" not in blob

    @pytest.mark.usefixtures("pre311_parser", "fixed_snapshot")
    def test_sentiment_category_medium_under_pre311_parser(self, monkeypatch):
        # Reproduces the original failing assertion 364: sentiment is Medium (not
        # Blocked) and its usable records reach the citation allowlist.
        from tradingagents.debate.evidence_manifest import build_citation_allowlist

        _capture_stocktwits(monkeypatch, _raw_stocktwits())
        with use_collector(SYMBOL, TARGET):
            stocktwits.fetch_stocktwits_messages(SYMBOL, start_date="2026-05-06", end_date=TARGET)
            out = _gate_node()(
                {"company_of_interest": SYMBOL, "trade_date": TARGET, "asset_type": "stock"}
            )
        cats = {g["category"]: g["quality_status"] for g in out["data_quality_group_statuses"]}
        assert cats["sentiment"] == "Medium"
        allowlist = build_citation_allowlist(out[GATE_EVIDENCE_RECORDS_KEY], TARGET)
        usable = [
            r
            for r in out[GATE_EVIDENCE_RECORDS_KEY]
            if r["category"] == "sentiment" and r["quality_status"] == "Medium"
        ]
        assert usable
        for r in usable:
            assert r["evidence_id"] in allowlist


# ---------------------------------------------------------------------------
# Future + Z source evidence is rejected as look-ahead (source-level evidence).
# ---------------------------------------------------------------------------


class TestFutureTerminalZSourceRejected:
    def test_future_terminal_z_sentiment_is_lookahead(self):
        # NFR-PIT-001 / INV-3: a terminal-Z posted_at AFTER the target must be
        # rejected at the source-evidence validation boundary (not merely a
        # future date returned by to_date).
        rec = build_sentiment_record(
            run_id=f"{TARGET}/{SYMBOL}",
            symbol_input=SYMBOL,
            symbol_normalized=SYMBOL,
            target_date=TARGET,
            source_name="stocktwits",
            native_label="Bullish",
            body="future post",
            posted_at="2026-06-01T12:00:00Z",
            author_ref="",
            lineage_key="stocktwits|future|future post",
            index=0,
        )
        results, exclusion = validate_sentiment_record(
            rec, expected_symbol=SYMBOL, target_date=TARGET
        )
        assert exclusion == "lookahead"
        assert any(r.status.value == "fail" for r in results)
        assert rec.observed_at == "2026-06-01"

    @pytest.mark.usefixtures("pre311_parser")
    def test_future_terminal_z_parsed_then_rejected(self):
        # Under the pre-3.11 simulation the future date still resolves (via the
        # repair) AND is then rejected as look-ahead — the repair never launders
        # a future record into validity.
        assert policy.to_date("2026-06-01T12:00:00Z") == date(2026, 6, 1)
        rec = build_sentiment_record(
            run_id=f"{TARGET}/{SYMBOL}",
            symbol_input=SYMBOL,
            symbol_normalized=SYMBOL,
            target_date=TARGET,
            source_name="stocktwits",
            native_label="Bullish",
            body="future post",
            posted_at="2026-06-01T12:00:00Z",
            author_ref="",
            lineage_key="stocktwits|future2|future post",
            index=0,
        )
        _results, exclusion = validate_sentiment_record(
            rec, expected_symbol=SYMBOL, target_date=TARGET
        )
        assert exclusion == "lookahead"
