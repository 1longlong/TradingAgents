"""Tests for the structured market snapshot (DQ gate step 1).

Offline: no network. ``load_ohlcv`` is monkeypatched to a fixed DataFrame, so
none of these reach yfinance. Covers no-look-ahead exclusion, truthful
yfinance/load_ohlcv provenance, structured values, injected ``fetched_at``,
structural indicator failure, and the backward-compatible Markdown API.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator

# Capture the real stockstats ``wrap`` at import time, BEFORE any monkeypatch.
# The indicator-failure fake needs to wrap a DataFrame with the actual
# stockstats implementation: calling ``validator.wrap`` from inside the fake
# after it was monkeypatched would recurse forever.
_REAL_WRAP = validator.wrap


def _sample_ohlcv() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame({
        "Date": dates,
        "Open": [c - 0.5 for c in closes],
        "High": [c + 1.0 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes,
        "Volume": [1_000_000 + i for i in range(len(dates))],
    })


def _with_future_row() -> pd.DataFrame:
    return pd.concat([
        _sample_ohlcv(),
        pd.DataFrame({
            "Date": [pd.Timestamp("2026-06-01")],
            "Open": [999.0], "High": [999.0], "Low": [999.0],
            "Close": [999.0], "Volume": [999],
        }),
    ], ignore_index=True)


@pytest.mark.unit
class TestStructuredSnapshotNoLookAhead:
    def test_excludes_future_rows(self, monkeypatch):
        data = _with_future_row()
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: data)
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00+00:00"
        )
        assert snap.latest_trading_row_date == "2026-05-13"
        # Expected close computed from the target-date row of the fixed frame.
        target_row = data[data["Date"] == pd.Timestamp("2026-05-13")].iloc[0]
        expected_close = str(Decimal(str(float(target_row["Close"]))).quantize(Decimal("0.00000001")))
        assert str(snap.latest_ohlcv.close.value) == expected_close
        # Future row's 999 close is excluded from the structured record.
        assert "999.00000000" not in {str(c.close.value) for c in snap.recent_closes}
        assert all(rc.date <= "2026-05-13" for rc in snap.recent_closes)

    def test_uses_previous_trading_day_on_weekend(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-16", fetched_at=None
        )
        # 2026-05-16 is a Saturday; latest row is Friday 2026-05-15.
        assert snap.latest_trading_row_date == "2026-05-15"


@pytest.mark.unit
class TestStructuredSnapshotValues:
    def _snap(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        return validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00+00:00"
        )

    def test_normalized_symbol_and_dates(self, monkeypatch):
        snap = self._snap(monkeypatch)
        assert snap.symbol_normalized == "COF"
        assert snap.requested_date == "2026-05-13"
        assert snap.latest_trading_row_date == "2026-05-13"

    def test_latest_ohlcv_accessible_without_markdown(self, monkeypatch):
        snap = self._snap(monkeypatch)
        assert snap.latest_ohlcv.close.value is not None
        assert snap.latest_ohlcv.high.value is not None
        assert snap.latest_ohlcv.low.value is not None
        assert snap.latest_ohlcv.open.value is not None
        assert snap.latest_ohlcv.volume.value is not None

    def test_indicators_accessible_without_markdown(self, monkeypatch):
        snap = self._snap(monkeypatch)
        assert snap.indicators, "expected at least one indicator"
        by_name = {i.name: i for i in snap.indicators}
        assert "boll_lb" in by_name and "rsi" in by_name
        assert all(i.status == validator.IndicatorStatus.COMPUTED for i in snap.indicators)

    def test_recent_closes_with_dates(self, monkeypatch):
        snap = self._snap(monkeypatch)
        assert snap.recent_closes, "expected recent closes"
        assert all(rc.date and rc.close.value is not None for rc in snap.recent_closes)
        assert len(snap.recent_closes) <= 30


@pytest.mark.unit
class TestProvenance:
    def test_truthful_source_name(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00+00:00"
        )
        assert snap.source_name == "yfinance"
        assert snap.source_tool == "load_ohlcv"
        # Never claims two independent sources.
        assert snap.source_name != "market_ohlcv"

    def test_default_source_tool_is_load_ohlcv(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00+00:00"
        )
        assert snap.source_tool == "load_ohlcv"


@pytest.mark.unit
class TestFetchedAt:
    def test_injected_fetched_at_normalized(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00+00:00"
        )
        assert snap.fetched_at == "2026-05-13T12:00:00Z"

    def test_none_produces_valid_utc_iso(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at=None
        )
        # Must be a well-formed ISO-8601 UTC timestamp.
        assert snap.fetched_at.endswith("Z")
        assert len(snap.fetched_at) == 20
        # Deterministic parse: value must survive a strict parse.
        import datetime as _dt
        _dt.datetime.fromisoformat(snap.fetched_at[:-1] + "+00:00")

    def test_invalid_fetched_at_raises(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot_data(
                "COF", "2026-05-13", fetched_at="not-a-timestamp"
            )


@pytest.mark.unit
class TestIndicatorFailure:
    def _fake_stats_frame(self, df: pd.DataFrame):
        """A stockstats-like frame that raises for ``rsi`` but is otherwise usable.

        The builder first reads ``frame[name]`` (to trigger calculation) then
        ``frame.iloc[-1][name]`` (to fetch the latest value). Returning the real
        wrapped frame except when ``name == "rsi"`` lets a single indicator fail
        structurally while the rest compute normally.
        """
        real = _REAL_WRAP(df.copy())

        class Row:
            def __init__(self, row):
                self._row = row

            def __getitem__(self, name):
                if name == "rsi":
                    raise ValueError("bad rsi window")
                return self._row[name]

        class Frame:
            def __getitem__(self, name):
                if name == "rsi":
                    raise ValueError("bad rsi window")
                return real[name]

            @property
            def iloc(self):
                return _IlocProxy(self)

        class _IlocProxy:
            def __init__(self, owner):
                self._owner = owner

            def __getitem__(self, idx):
                if idx == -1:
                    return Row(real.iloc[-1])
                return real.iloc[idx]

        return Frame()

    def test_indicator_failure_is_structural(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())

        def _wrap(df):
            return self._fake_stats_frame(df)

        monkeypatch.setattr(validator, "wrap", _wrap)
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00Z"
        )
        by_name = {i.name: i for i in snap.indicators}
        assert by_name["rsi"].value is None
        assert by_name["rsi"].status == validator.IndicatorStatus.FAILED
        assert by_name["rsi"].error == "ValueError"
        assert by_name["rsi"].error_message
        others = [i for i in snap.indicators if i.name != "rsi"]
        assert others, "expected other indicators to compute"
        assert all(o.value is not None for o in others)
        assert len(snap.recent_closes) > 0  # snapshot did not sink

    def test_failed_indicator_markdown_placeholder(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())

        def _wrap(df):
            return self._fake_stats_frame(df)

        monkeypatch.setattr(validator, "wrap", _wrap)
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00Z"
        )
        by_name = {i.name: i for i in snap.indicators}
        assert by_name["rsi"].display == "N/A (ValueError)"
        assert by_name["rsi"].display.startswith("N/A (")

    def test_indicator_status_enum(self):
        assert validator.IndicatorStatus.COMPUTED.value == "computed"
        assert validator.IndicatorStatus.FAILED.value == "failed"


@pytest.mark.unit
class TestMarkdownBackCompat:
    def test_renderer_delegates_to_structured_data(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        # Capture the real structured builder BEFORE replacing it, so the spy
        # produces real output instead of recursing through the patched symbol.
        real_builder = validator.build_verified_market_snapshot_data
        calls = {}

        def _spy(*args, **kwargs):
            calls["called"] = True
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(validator, "build_verified_market_snapshot_data", _spy)
        md = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert calls.get("called") is True
        assert "Verified market data snapshot for COF" in md

    def test_markdown_has_required_headers_and_content(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        md = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "## Verified market data snapshot for COF" in md
        assert "Requested analysis date: 2026-05-13" in md
        assert "Latest trading row used: 2026-05-13" in md
        assert "### Latest verified OHLCV row" in md
        assert "### Verified technical indicators (latest row)" in md
        assert "### Recent verified closes" in md
        assert "| Close |" in md or "| Open |" in md
        assert "boll_lb" in md

    def test_markdown_int_vs_float_display(self, monkeypatch):
        # Derive the expected display from the structured snapshot so this never
        # hardcodes a magic row value.
        monkeypatch.setattr(validator, "load_ohlcv",
                            lambda s, d, fill_gaps=True: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot_data(
            "COF", "2026-05-13", fetched_at="2026-05-13T12:00:00Z"
        )
        md = validator._render_verified_market_snapshot(snap)
        # The renderer must echo the snapshot's preserved display for Volume.
        expected = snap.latest_ohlcv.volume.display
        assert f"| Volume | {expected} |" in md
        # An integer Volume renders with no decimal point (preserved _fmt), and
        # the value is numeric.
        assert "." not in expected
        assert expected.isdigit()
