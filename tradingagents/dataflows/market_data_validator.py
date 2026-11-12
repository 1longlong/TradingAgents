"""Deterministic market-data verification snapshot.

The market analyst is an LLM that can confabulate exact numbers — citing a
Bollinger band or a "historically validated bounce" that the underlying data
doesn't support (#830). This module computes a ground-truth snapshot (latest
OHLCV row on or before the analysis date, common indicators, recent closes)
the analyst is told to treat as the source of truth for any exact numeric
claim. Deterministic, no LLM involved.

Two surfaces are exposed:

- :func:`build_verified_market_snapshot_data` — the **structured** result.
  Normalized symbol, requested date, latest trading-row date, raw OHLCV,
  indicator values (failures held structurally, never as numbers), recent
  closes, and source/provenance metadata. This is the deterministic feeder for
  downstream ``EvidenceRecord`` adapters. It represents the underlying market
  source/provenance only — it is not, and must not be presented as, two
  independent production sources.
- :func:`build_verified_market_snapshot` — the **Markdown** renderer, kept for
  backward compatibility. It is implemented as a pure renderer over the
  structured result and never parses Markdown back into evidence.
"""

from __future__ import annotations

import numbers
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.stockstats_utils import load_ohlcv

# A fixed, common indicator set so the snapshot is the same shape every run.
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)

# Truthful provenance: this path reads OHLCV through ``load_ohlcv``, which
# fetches from yfinance. It is a single underlying source — deliberately NOT a
# claim of two independent production sources.
SNAPSHOT_SOURCE_NAME = "yfinance"
SNAPSHOT_SOURCE_TOOL = "load_ohlcv"


class IndicatorStatus(str, Enum):
    """Whether an indicator computed or failed to compute."""

    COMPUTED = "computed"
    FAILED = "failed"


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string with second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_iso(value: str | None) -> str:
    """Return a valid UTC ISO-8601 string for ``value`` or raise ``ValueError``.

    ``None`` becomes the current UTC time. A supplied value is parsed; a naive
    value is treated as UTC (so it is already a valid ISO string), a tz-aware
    value is converted to UTC. Any value that is not parseable yields a
    ``ValueError`` rather than silently emitting a malformed timestamp.
    """
    if value is None:
        return _now_iso()
    parsed = value.strip()
    if not parsed:
        raise ValueError("fetched_at must be a non-empty ISO timestamp or None")
    text = parsed
    if parsed.endswith("Z"):
        text = parsed[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"fetched_at must be an ISO-8601 timestamp, got {parsed!r}"
        ) from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """OHLCV on or before curr_date, date-sorted. Raises if nothing usable.

    ``load_ohlcv`` already normalizes the Date column and filters out
    look-ahead rows, but we re-apply the cutoff defensively — this is a
    verification path, so it must not trust its input to be pre-filtered.
    """
    # As reported: this snapshot is quoted by the agents as exact prices, so a
    # gap-filled cell would put the previous session's number under this date.
    data = load_ohlcv(symbol, curr_date, fill_gaps=False)
    if data is None or data.empty:
        raise ValueError(f"No OHLCV data available for {symbol}.")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        raise ValueError(f"No OHLCV rows on or before {curr_date} for {symbol}.")
    return df


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _to_decimal(value) -> Decimal | None:
    """Convert a numeric OHLCV/indicator value to a quantized ``Decimal``.

    ``None`` / NaN / non-finite / non-numeric returns ``None`` so a value that
    did not compute is represented structurally (an absent value plus a status),
    never as a coerced number. Floats go through ``str()`` to avoid binary
    float noise; numpy integer/float scalars are handled via ``numbers.Real`` so
    integral OHLCV/Volume cells (which pandas reports as ``numpy.int64``, not a
    plain ``int``) still convert to a ``Decimal``. This is a display-friendly
    quantization (8 decimal places) used for the structured record, not a
    financial comparison tolerance.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        magnitude = value
    elif isinstance(value, numbers.Real):
        # Covers int, float, numpy int/float scalars. Reject non-finite first.
        if isinstance(value, numbers.Integral) and not isinstance(value, bool):
            number = int(value)
        else:
            number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        magnitude = Decimal(str(number))
    else:
        return None
    if not magnitude.is_finite():
        return None
    return magnitude.quantize(Decimal("0.00000001"))


@dataclass(frozen=True)
class StructuredIndicator:
    """One indicator in the structured snapshot.

    ``value`` is the quantized ``Decimal`` (``None`` when the indicator did not
    compute). ``status`` is an ``IndicatorStatus``; a failed indicator carries
    ``error`` (a structural failure marker) and an ``error_message``. ``display``
    is the exact string the Markdown renderer emits, so the renderer is a pure
    pass-through and a failure never becomes a numeric value.
    """

    name: str
    value: Decimal | None
    status: IndicatorStatus
    error: str | None = None
    error_message: str | None = None
    display: str = "N/A"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": str(self.value) if self.value is not None else None,
            "status": self.status.value,
            "error": self.error,
            "error_message": self.error_message,
            "display": self.display,
        }


@dataclass(frozen=True)
class StructuredVisibleField:
    """A numeric field plus its precomputed display string.

    The builder computes ``display`` with the same ``_fmt`` used historically,
    so the Markdown renderer is a pure pass-through and preserves the exact
    int-as-int / float-as-two-decimals behaviour of the original output. The
    quantized ``value`` is what a downstream ``EvidenceRecord`` adapter uses;
    the raw float/int type is not recoverable from a ``Decimal``, so keeping
    the original render string here is what makes the renderer byte-faithful.
    """

    value: Decimal | None
    display: str


def _structured_display(value) -> StructuredVisibleField:
    return StructuredVisibleField(value=_to_decimal(value), display=_fmt(value))


@dataclass(frozen=True)
class StructuredOHLCV:
    """Latest verified OHLCV row with quantized numeric fields."""

    open: StructuredVisibleField
    high: StructuredVisibleField
    low: StructuredVisibleField
    close: StructuredVisibleField
    volume: StructuredVisibleField


def _to_structured_ohlcv(row) -> StructuredOHLCV:
    return StructuredOHLCV(
        open=_structured_display(row.get("Open")),
        high=_structured_display(row.get("High")),
        low=_structured_display(row.get("Low")),
        close=_structured_display(row.get("Close")),
        volume=_structured_display(row.get("Volume")),
    )


@dataclass(frozen=True)
class StructuredRecentClose:
    """One recent close: its date (``YYYY-MM-DD``) and quantized close."""

    date: str
    close: StructuredVisibleField


@dataclass(frozen=True)
class StructuredSnapshot:
    """The deterministic ground-truth market snapshot, as structured data.

    Provides everything a later :class:`~tradingagents.evidence.models.EvidenceRecord`
    adapter needs: normalized symbol, requested date, latest trading-row date,
    latest raw OHLCV, indicator values (failures held structurally), recent
    closes with dates, and source/provenance metadata.

    This represents the underlying market source/provenance only. It is **not**
    a claim of two independent production sources; a downstream EvidenceRecord
    adapter must set source independence accordingly (single source here).
    """

    symbol_normalized: str
    requested_date: str
    latest_trading_row_date: str
    latest_ohlcv: StructuredOHLCV
    indicators: tuple[StructuredIndicator, ...]
    recent_closes: tuple[StructuredRecentClose, ...]
    source_name: str
    source_tool: str
    source_ref: str | None
    fetched_at: str

    def to_dict(self) -> dict:
        return {
            "symbol_normalized": self.symbol_normalized,
            "requested_date": self.requested_date,
            "latest_trading_row_date": self.latest_trading_row_date,
            "latest_ohlcv": {
                "open": str(self.latest_ohlcv.open.value) if self.latest_ohlcv.open.value is not None else None,
                "high": str(self.latest_ohlcv.high.value) if self.latest_ohlcv.high.value is not None else None,
                "low": str(self.latest_ohlcv.low.value) if self.latest_ohlcv.low.value is not None else None,
                "close": str(self.latest_ohlcv.close.value) if self.latest_ohlcv.close.value is not None else None,
                "volume": str(self.latest_ohlcv.volume.value) if self.latest_ohlcv.volume.value is not None else None,
            },
            "indicators": [ind.to_dict() for ind in self.indicators],
            "recent_closes": [
                {"date": rc.date, "close": str(rc.close.value) if rc.close.value is not None else None}
                for rc in self.recent_closes
            ],
            "source_name": self.source_name,
            "source_tool": self.source_tool,
            "source_ref": self.source_ref,
            "fetched_at": self.fetched_at,
        }


def build_verified_market_snapshot_data(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
    source_tool: str = SNAPSHOT_SOURCE_TOOL,
    fetched_at: str | None = None,
    source_ref: str | None = None,
) -> StructuredSnapshot:
    """Build the structured ground-truth market snapshot.

    Uses the same ``_verified_rows`` cutoff (no look-ahead). Indicator
    calculation failures are captured structurally (``IndicatorStatus.FAILED``,
    ``value=None``, ``display`` holding the ``N/A (... )`` marker) and never
    sink the snapshot or become a numeric value.

    ``source_name`` is the single underlying market source this path reads
    (yfinance via ``load_ohlcv``) — it is deliberately **not** presented as two
    independent production sources. ``fetched_at`` defaults to the current UTC
    time; a supplied value must be a valid ISO-8601 timestamp or it raises
    ``ValueError``, so the structured timestamp is always well-formed.
    """
    from tradingagents.dataflows.symbol_utils import normalize_symbol

    df = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    structured_indicators: list[StructuredIndicator] = []
    for name in selected:
        try:
            stock_df[name]  # triggers stockstats calculation
            raw = stock_df.iloc[-1][name]
            display = _fmt(raw)
            structured_indicators.append(
                StructuredIndicator(
                    name=name,
                    value=_to_decimal(raw),
                    status=IndicatorStatus.COMPUTED,
                    display=display,
                )
            )
        except Exception as exc:  # noqa: BLE001 — one bad indicator shouldn't sink the snapshot
            structured_indicators.append(
                StructuredIndicator(
                    name=name,
                    value=None,
                    status=IndicatorStatus.FAILED,
                    error=type(exc).__name__,
                    error_message=str(exc),
                    display=f"N/A ({type(exc).__name__})",
                )
            )

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    structured_recent: list[StructuredRecentClose] = []
    for _, row in recent.iterrows():
        structured_recent.append(
            StructuredRecentClose(
                date=_fmt(row["Date"]),
                close=_structured_display(row.get("Close")),
            )
        )

    return StructuredSnapshot(
        symbol_normalized=normalize_symbol(symbol),
        requested_date=str(curr_date),
        latest_trading_row_date=latest_date,
        latest_ohlcv=_to_structured_ohlcv(latest),
        indicators=tuple(structured_indicators),
        recent_closes=tuple(structured_recent),
        source_name=SNAPSHOT_SOURCE_NAME,
        source_tool=source_tool,
        source_ref=source_ref,
        fetched_at=_normalize_iso(fetched_at),
    )


def _render_verified_market_snapshot(snapshot: StructuredSnapshot) -> str:
    """Render a ``StructuredSnapshot`` to Markdown.

    Pure transformation: every value/display comes from the structured record,
    so this never parses Markdown and the content is materially identical to the
    historical output.
    """
    requested = snapshot.requested_date

    lines = [
        f"## Verified market data snapshot for {snapshot.symbol_normalized.upper()}",
        "",
        f"- Requested analysis date: {requested}",
        f"- Latest trading row used: {snapshot.latest_trading_row_date}",
        "- Rows after the requested analysis date are excluded before verification.",
        "",
        "### Latest verified OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for ohlcv_field in ("open", "high", "low", "close", "volume"):
        field_value = getattr(snapshot.latest_ohlcv, ohlcv_field)
        lines.append(f"| {ohlcv_field.capitalize()} | {field_value.display} |")

    lines += ["", "### Verified technical indicators (latest row)", "",
              "| Indicator | Value |", "|---|---:|"]
    for ind in snapshot.indicators:
        lines.append(f"| {ind.name} | {ind.display} |")

    lines += ["",
              f"### Recent verified closes (last {len(snapshot.recent_closes)} rows)",
              "", "| Date | Close |", "|---|---:|"]
    for rc in snapshot.recent_closes:
        lines.append(f"| {rc.date} | {rc.close.display} |")

    lines += [
        "",
        "Use this snapshot as the source of truth for exact OHLCV, price-level, "
        "and indicator-value claims. If another tool output conflicts with it, "
        "flag the discrepancy rather than inventing a reconciled number. Do not "
        "claim historical validation, support/resistance bounces, or exact "
        "percentage moves unless directly supported by tool output with concrete "
        "dates and prices.",
    ]
    return "\n".join(lines)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """Render a ground-truth snapshot as Markdown (backward-compatible).

    Implemented as a renderer over :func:`build_verified_market_snapshot_data`;
    the classic Markdown contract (``Verified market data snapshot``, ``Latest
    trading row used``, section headers, ``N/A (... error type)`` for failed
    indicators) is preserved and content is materially identical.
    """
    snapshot = build_verified_market_snapshot_data(
        symbol,
        curr_date,
        look_back_days=look_back_days,
        indicators=indicators,
    )
    return _render_verified_market_snapshot(snapshot)
