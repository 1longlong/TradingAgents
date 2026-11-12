"""Truthful adapter from a structured market snapshot to evidence records.

This module converts a :class:`~tradingagents.dataflows.market_data_validator.StructuredSnapshot`
into one :class:`~tradingagents.evidence.models.EvidenceRecord` per OHLCV metric
on the latest verified trading row.

Design rules (authoritative):

- **Truthful**: it reuses the structured numeric values, dates, and provenance
  from the snapshot. It *never* parses the Markdown renderer, and it *never*
  invents a second source. The snapshot's ``source_name``/``source_tool`` are
  carried through unchanged, so the adapter is honest that this is a single
  underlying source (yfinance via ``load_ohlcv``).
- **No invented quote currency**: the snapshot does not know the quote
  currency, so the price unit is an explicit adapter argument
  (``price_unit``), defaulting to the truthful neutral value
  ``native_quote_currency``. Volume stays ``shares``.
- **Stable, deterministic evidence IDs**: ``<run_id>/<category>/<source>/<metric>/<index>``.
  The index is a **fixed stable sequence index (0)** for the single
  latest-row adapter, because the metric already differentiates the records and
  the index must not change when ``look_back_days`` changes. The resulting ID is
  therefore stable across runs for a given ``(symbol, requested_date)`` at any
  ``look_back_days``.
- **Metric criticality**: ``close`` and ``volume`` are ``CRITICAL``;
  ``open``/``high``/``low`` are ``IMPORTANT``. ``observed_at`` is the trading
  row's date, ``target_date`` is the requested analysis date, and units are
  explicit.
- **Category**: the authoritative topic-level Gate category is ``market``.
"""

from __future__ import annotations

from decimal import Decimal

from tradingagents.dataflows.market_data_validator import StructuredSnapshot
from tradingagents.evidence.models import (
    EvidenceRecord,
    QualityStatus,
)
from tradingagents.evidence.policy import MarketRecordPolicy

# Streaming OHLCV metric fields present on the structured snapshot, in a fixed
# order. ``close`` and ``volume`` are critical; the rest are important.
_OHLCV_METRICS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

# Truthful neutral price unit: the snapshot does not expose the quote currency,
# so we must not invent one. Volume is denominated in shares.
NATIVE_QUOTE_CURRENCY = "native_quote_currency"
_VOLUME_UNIT = "shares"

# Authoritative topic-level Gate category for market evidence.
MARKET_CATEGORY = "market"

# The single latest-row adapter always uses a fixed stable sequence index so the
# evidence ID does not change when ``look_back_days`` changes; the metric already
# differentiates the records.
_STABLE_INDEX = 0


def _fmt_dec(value: Decimal | None) -> str:
    """Fixed-precision string for a Decimal (or ``""`` for ``None``)."""
    if value is None:
        return ""
    return str(value)


def make_market_evidence_id(
    run_id: str,
    category: str,
    source_name: str,
    metric_name: str,
    index: int,
) -> str:
    """Build the stable deterministic evidence ID.

    ``index`` is the stable sequence index of the trading row. It is kept free of
    a timestamp so the ID is stable across runs for a given
    ``(symbol, requested_date)`` and does not vary with ``look_back_days``.
    """
    return "/".join([run_id, category, source_name, metric_name, str(index)])


def build_market_evidence_records(
    snapshot: StructuredSnapshot,
    run_id: str,
    *,
    price_unit: str = NATIVE_QUOTE_CURRENCY,
    ticker_input: str | None = None,
    record_policy: MarketRecordPolicy | None = None,
) -> list[EvidenceRecord]:
    """Adapt a ``StructuredSnapshot`` into market OHLCV ``EvidenceRecord``s.

    One record per metric on the latest verified trading row. ``observed_at`` is
    the trading row date, ``target_date`` is the requested analysis date, and
    units are explicit per metric. The source/provenance is carried straight
    through from the snapshot — never a second source, never Markdown parsing.

    Args:
        snapshot: The structured ground-truth snapshot (single source).
        run_id: The run identifier to stamp on each record.
        price_unit: The unit for ``open``/``high``/``low``/``close``. Defaults to
            the truthful neutral ``native_quote_currency`` because the snapshot
            does not expose the quote currency; pass an explicit unit if you know
            it. Volume is always ``shares``.
        ticker_input: The original (user/broker) ticker, retained as
            ``ticker_input``; ``ticker_normalized`` always comes from the
            snapshot's normalized symbol.
        record_policy: Optional per-record metric criticality policy.

    Returns:
        A list of ``EvidenceRecord`` objects, one per OHLCV metric, in a stable
        order (``open``, ``high``, ``low``, ``close``, ``volume``).
    """
    policy = record_policy or MarketRecordPolicy()
    latest = snapshot.latest_ohlcv
    criticality_for = policy.criticality_for
    input_ticker = snapshot.symbol_normalized if ticker_input is None else ticker_input

    records: list[EvidenceRecord] = []
    field_values: dict[str, Decimal | None] = {
        "open": latest.open.value,
        "high": latest.high.value,
        "low": latest.low.value,
        "close": latest.close.value,
        "volume": latest.volume.value,
    }

    for metric in _OHLCV_METRICS:
        normalized = field_values[metric]
        evidence_id = make_market_evidence_id(
            run_id=run_id,
            category=MARKET_CATEGORY,
            source_name=snapshot.source_name,
            metric_name=metric,
            index=_STABLE_INDEX,
        )
        is_price = metric in ("open", "high", "low", "close")
        unit = price_unit if is_price else _VOLUME_UNIT
        records.append(
            EvidenceRecord.build(
                evidence_id=evidence_id,
                run_id=run_id,
                ticker_input=input_ticker,
                ticker_normalized=snapshot.symbol_normalized,
                asset_type="stock",
                category=MARKET_CATEGORY,
                metric_name=metric,
                value_raw=_fmt_dec(normalized),
                value_normalized=normalized,
                unit_raw=unit,
                unit_normalized=unit,
                source_name=snapshot.source_name,
                source_ref=snapshot.source_ref or snapshot.source_tool,
                observed_at=snapshot.latest_trading_row_date,
                fetched_at=snapshot.fetched_at,
                target_date=snapshot.requested_date,
                criticality=criticality_for(metric),
                validation_results=[],
                # Freshness/format results are attached by the validator; here
                # we only set a provisional quality status the validator owns.
                quality_status=QualityStatus.LOW,
                quality_reasons=["unvalidated"],
            )
        )
    return records
