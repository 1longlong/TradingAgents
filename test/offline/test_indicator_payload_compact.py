"""The indicator series is context, and must stay exactly that much context.

``get_indicators`` used to append the indicator's own definition to every
response and print values at full float precision. Neither carried information
the pipeline can use:

* the definition text is already in the market analyst's system prompt, and is
  identical on every call for a given indicator;
* the authoritative source of truth for exact claims,
  ``get_verified_market_snapshot``, renders every indicator at 2 decimal places
  (``market_data_validator._fmt``), so extra precision can never survive into a
  verified claim.

These tests pin the equivalence: the series must keep every date, every value
(within 0.005, i.e. ``round(x, 2)``), and every missing-data marker.
"""
import inspect

import pytest

from tradingagents.dataflows import y_finance

pytestmark = pytest.mark.unit


DATES = [
    "2026-09-23", "2026-09-22", "2026-09-21", "2026-09-20", "2026-09-19",
    "2026-09-18",
]

# The window walk emits every calendar day it steps over, so a date absent from
# the fixture is rendered as a weekend/holiday marker -- which is what
# `test_non_trading_day_marker_is_still_emitted` pins. The base fixture therefore
# covers every date except 2026-09-19 (a Saturday), which is absent on purpose.
SERIES = {
    "2026-09-23": 55.84844444444444,
    "2026-09-22": 62.135802443,
    "2026-09-21": 41.41203703703704,
    "2026-09-20": None,          # stockstats NaN row -> "N/A"
    "2026-09-18": 70.0,
}


def _series(**overrides):
    series = dict(SERIES)
    series.update(overrides)
    return series


def _render(monkeypatch, indicator="rsi", series=None, look_back=5,
            cur="2026-09-23"):
    """Render the window payload with the vendor fetch stubbed out."""
    series = _series() if series is None else series
    monkeypatch.setattr(
        y_finance, "_get_stock_stats_bulk", lambda *a, **k: dict(series)
    )
    return y_finance.get_stock_stats_indicators_window(
        "NVDA", indicator, cur, look_back
    )


def _rows(payload):
    """(date, value) pairs, skipping the header and blank lines."""
    out = []
    for line in payload.splitlines():
        if not line or line.startswith("## "):
            continue
        date, sep, value = line.partition(": ")
        assert sep == ": ", f"row lost its 'date: value' shape: {line!r}"
        out.append((date, value))
    return out


# --- R1: equivalence --------------------------------------------------------

def test_every_date_is_kept_and_no_row_is_added(monkeypatch):
    payload = _render(monkeypatch)
    dates = [d for d, _ in _rows(payload)]
    # The window walk covers every calendar day newest-first, including the
    # Saturday the fixture omits; that row must be the holiday marker, not a
    # silent gap.
    assert dates == DATES, dates


def test_values_are_the_original_rounded_to_two_decimals(monkeypatch):
    payload = _render(monkeypatch)
    original = _series()
    for date, value in _rows(payload):
        if date not in original:
            assert value == "N/A: Not a trading day (weekend or holiday)", date
            continue
        expected = original[date]
        if expected is None:
            assert value == "N/A", f"{date}: missing value lost its N/A marker"
            continue
        assert float(value) == round(float(expected), 2), (
            f"{date}: {value} != round({expected}, 2)"
        )


@pytest.mark.parametrize("raw,expected", [
    (55.84844444444444, "55.85"),
    (62.135802443, "62.14"),
    (70.0, "70.00"),
    (0.30000000000000004, "0.30"),
    (226.0, "226.00"),
    (-1.005, "-1.00"),  # f-string %.2f on the nearest binary float
])
def test_format_is_stable_two_decimal_text(raw, expected):
    assert y_finance._format_indicator_value(raw) == expected


def test_missing_values_still_render_as_na():
    assert y_finance._format_indicator_value(None) == "N/A"
    assert y_finance._format_indicator_value(float("nan")) == "N/A"


# --- R1: window identity ----------------------------------------------------

def test_window_header_is_unchanged(monkeypatch):
    payload = _render(monkeypatch)
    assert payload.startswith("## rsi values from 2026-09-18 to 2026-09-23:")


def test_non_trading_day_marker_is_still_emitted(monkeypatch):
    # A date missing from the vendor series is NOT a missing value: it is a
    # weekend/holiday marker, and that distinction must survive.
    series = {d: v for d, v in _series().items() if d != "2026-09-20"}
    payload = _render(monkeypatch, series=series)
    rows = dict(_rows(payload))
    assert rows["2026-09-20"] == "N/A: Not a trading day (weekend or holiday)"


# --- R3: the definition is not lost, only de-duplicated ---------------------

def test_payload_no_longer_repeats_the_indicator_definition(monkeypatch):
    payload = _render(monkeypatch)
    assert "Usage:" not in payload
    assert "Tips:" not in payload
    assert "No description available." not in payload


def test_the_definition_remains_in_the_market_analyst_system_prompt():
    """R3b: removed from the tool result, retained where the model reads it.

    Checks every one of the 13 indicators, not a sample: an indicator whose
    definition is in neither place would silently lose its usage guidance.
    """
    from tradingagents.agents.analysts import market_analyst

    prompt_src = inspect.getsource(market_analyst)
    definitions = {
        "close_50_sma": "A medium-term trend indicator",
        "close_200_sma": "A long-term trend benchmark",
        "close_10_ema": "A responsive short-term average",
        "macd": "Computes momentum via differences of EMAs",
        "macds": "An EMA smoothing of the MACD line",
        "macdh": "Shows the gap between the MACD line and its signal",
        "rsi": "Measures momentum to flag overbought/oversold conditions",
        "boll": "A 20 SMA serving as the basis for Bollinger Bands",
        "boll_ub": "Typically 2 standard deviations above the middle line",
        "boll_lb": "Typically 2 standard deviations below the middle line",
        "atr": "Averages true range to measure volatility",
        "vwma": "A moving average weighted by volume",
        "mfi": "The Money Flow Index is a momentum indicator",
    }
    missing = [name for name, phrase in definitions.items() if phrase not in prompt_src]
    assert not missing, (
        "indicator definition lost from BOTH the tool payload and the analyst "
        f"prompt: {missing}"
    )


# --- R2: coverage -----------------------------------------------------------

def test_all_supported_indicators_still_render(monkeypatch):
    supported = [
        "close_50_sma", "close_200_sma", "close_10_ema",
        "macd", "macds", "macdh",
        "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi",
    ]
    for indicator in supported:
        payload = _render(monkeypatch, indicator=indicator)
        assert payload.startswith(f"## {indicator} values from "), indicator
        assert _rows(payload), f"{indicator}: rendered no rows"


def test_an_unsupported_indicator_still_raises_and_names_the_valid_ones(monkeypatch):
    with pytest.raises(ValueError) as excinfo:
        _render(monkeypatch, indicator="not_an_indicator")
    message = str(excinfo.value)
    assert "not supported" in message
    assert "rsi" in message and "macd" in message


# --- R3c: the fallback path formats identically -----------------------------

def test_fallback_path_uses_the_same_number_format(monkeypatch):
    # The per-day fallback must not reintroduce full-precision values, or the
    # two paths would disagree whenever the bulk fetch fails. `stockstats`
    # yields floats, so the stub returns a float exactly as the real
    # `get_stockstats_indicator` leaf would.
    def boom(*args, **kwargs):
        raise RuntimeError("bulk fetch failed")

    monkeypatch.setattr(y_finance, "_get_stock_stats_bulk", boom)
    monkeypatch.setattr(
        y_finance.StockstatsUtils, "get_stock_stats",
        staticmethod(lambda *a, **k: 55.84844444444444),
    )
    payload = y_finance.get_stock_stats_indicators_window(
        "NVDA", "rsi", "2026-09-23", 2
    )
    values = [v for _, v in _rows(payload)]
    assert values, "fallback rendered no rows"
    assert all(v == "55.85" for v in values), values


def test_bulk_nan_and_bare_none_both_render_as_na():
    # `_get_stock_stats_bulk` returns "N/A" for a NaN row; the window builder
    # must not leak a Python `None` into the table for the same condition.
    assert y_finance._format_indicator_value(None) == "N/A"
    assert y_finance._format_indicator_value(float("nan")) == "N/A"


def test_already_rendered_markers_pass_through_unchanged():
    # Formatting at the render point must be idempotent: the weekend marker and
    # the bulk helper's own "N/A" are strings, not numbers.
    weekend = "N/A: Not a trading day (weekend or holiday)"
    assert y_finance._format_indicator_value(weekend) == weekend
    assert y_finance._format_indicator_value("N/A") == "N/A"
