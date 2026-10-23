"""The five deterministic validation classes for market evidence.

This module validates market/OHLCV :class:`~tradingagents.evidence.models.EvidenceRecord`
objects against the five authoritative validation classes:

1. **Completeness** — every authoritative common required field present
   (``ticker_normalized``, ``category``, ``metric_name``, ``source_name``,
   ``observed_at``, ``fetched_at``, ``target_date``, plus numeric value and
   unit for OHLCV); sentinel strings fail.
2. **Freshness / Look-ahead** — ``observed_at`` on/before ``target_date``, the
   freshness age within the policy's business-day width, and ``target_date``
   agrees with the requested date. Malformed dates fail rather than being
   silently accepted.
3. **Format / Numeric legality** — finite positive OHLC, nonnegative volume,
   and the OHLC ordering relationships, validated per isolated row.
4. **Asset applicability** — ticker/asset matches the expected instrument.
5. **Cross-source consistency** — per (ticker, metric, observed_at, unit)
   group; independent sources agree within the per-metric tolerance. Order
   independent; median reference for 3+ sources, symmetric comparison for 2.

Every result carries ``rule_id``, ``expected``, ``actual``, ``message`` and
``evidence_id``. Sentinel strings such as ``NO_DATA_AVAILABLE`` and
``DATA_UNAVAILABLE`` **fail** rather than count as evidence.

This layer is pure and LLM-free: it only inspects ``EvidenceRecord`` values and
the deterministic :class:`~tradingagents.evidence.policy.MarketPolicy`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from tradingagents.evidence.models import (
    EvidenceRecord,
    ValidationClass,
    ValidationResult,
    ValidationStatus,
)
from tradingagents.evidence.policy import (
    MarketPolicy,
    MetricTolerance,
    count_business_days,
    to_date,
)

# Sentinel strings that must never count as evidence. A value that is one of
# these (exactly, ignoring case/whitespace) is a completeness/format failure.
MARKET_SENTINEL_STRINGS: frozenset[str] = frozenset(
    {"NO_DATA_AVAILABLE", "DATA_UNAVAILABLE"}
)

_PRICE_METRICS = ("open", "high", "low", "close")
_VOLUME_METRIC = "volume"

# Authoritative common required fields for an OHLCV market record.
REQUIRED_FIELDS = (
    "ticker_normalized",
    "category",
    "metric_name",
    "source_name",
    "observed_at",
    "fetched_at",
    "target_date",
)

RULE_COMPLETENESS_REQUIRED = "market.completeness.required_fields"
RULE_COMPLETENESS_SENTINEL = "market.completeness.sentinel"
RULE_FRESHNESS_LOOKAHEAD = "market.freshness.lookahead"
RULE_FRESHNESS_STALE = "market.freshness.stale"
RULE_FRESHNESS_TARGET_AGREEMENT = "market.freshness.target_date_agreement"
RULE_FRESHNESS_MALFORMED_DATE = "market.freshness.malformed_date"
RULE_FORMAT_NUMERIC = "market.format.numeric"
RULE_FORMAT_OHLC = "market.format.ohlc_relationships"
RULE_ASSET_TICKER = "market.asset.ticker_match"
RULE_ASSET_TYPE = "market.asset.type_match"
RULE_CROSS_SOURCE = "market.cross_source.consistency"


def is_sentinel(record: EvidenceRecord) -> bool:
    """True if the record's raw value is a known sentinel marker."""
    text = (record.value_raw or "").strip().upper()
    return text in MARKET_SENTINEL_STRINGS


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_date(value) -> date | None:
    """Parse a date; ``None`` when the value is blank or not parseable."""
    return to_date(value)


def _is_malformed_date(value) -> bool:
    """True if ``value`` is a present but non-parseable date string."""
    if _is_blank(value):
        return False
    return _parse_date(value) is None


def _rel_deviation(
    a: Decimal | None, b: Decimal | None, reference: Decimal | None
) -> Decimal | None:
    """Relative deviation of ``a`` vs ``b`` normalized by ``reference``."""
    if a is None or b is None or reference is None:
        return None
    if reference == 0 or not reference.is_finite():
        return None
    return (abs(a - b) / reference).quantize(Decimal("0.0001"))


def _result(
    record: EvidenceRecord,
    rule_id: str,
    validation_class: ValidationClass,
    status: ValidationStatus,
    expected,
    actual,
    message: str,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        validation_class=validation_class,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        evidence_id=record.evidence_id,
    )


# ---------------------------------------------------------------------------
# Per-record checks
# ---------------------------------------------------------------------------


def check_completeness(record: EvidenceRecord) -> ValidationResult:
    """Completeness: all authoritative common fields present; no sentinels."""
    if is_sentinel(record):
        return _result(
            record,
            RULE_COMPLETENESS_SENTINEL,
            ValidationClass.COMPLETENESS,
            ValidationStatus.FAIL,
            "a real value",
            record.value_raw,
            "Sentinel data marker must not count as evidence.",
        )
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        value = getattr(record, field)
        if _is_blank(value):
            missing.append(field)
    if record.value_normalized is None:
        missing.append("value_normalized")
    if not (record.value_raw or "").strip():
        missing.append("value_raw")
    if not record.unit_raw:
        missing.append("unit_raw")
    if missing:
        return _result(
            record,
            RULE_COMPLETENESS_REQUIRED,
            ValidationClass.COMPLETENESS,
            ValidationStatus.FAIL,
            "all required fields present",
            ", ".join(missing),
            f"Missing required field(s): {', '.join(missing)}.",
        )
    return _result(
        record,
        RULE_COMPLETENESS_REQUIRED,
        ValidationClass.COMPLETENESS,
        ValidationStatus.PASS,
        "all required fields present",
        "present",
        "All required fields present.",
    )


def check_target_date_agreement(
    record: EvidenceRecord, requested_target_date: str
) -> ValidationResult:
    """Ensure the record's ``target_date`` agrees with the requested date."""
    if _is_malformed_date(record.target_date):
        return _result(
            record,
            RULE_FRESHNESS_MALFORMED_DATE,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            f"a valid date matching {requested_target_date!r}",
            repr(record.target_date),
            "Malformed target_date must not be accepted.",
        )
    record_target = _parse_date(record.target_date)
    requested = _parse_date(requested_target_date)
    if requested is None:
        # The requested date itself is malformed; this is a caller bug and must
        # not silently validate. Fail closed.
        return _result(
            record,
            RULE_FRESHNESS_TARGET_AGREEMENT,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            "a valid requested target_date",
            repr(requested_target_date),
            "Requested target_date is malformed; cannot validate.",
        )
    if record_target is None:
        return _result(
            record,
            RULE_FRESHNESS_TARGET_AGREEMENT,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.NOT_APPLICABLE,
            f"target_date == {requested}",
            repr(record.target_date),
            "target_date absent (completeness owns the failure).",
        )
    if record_target != requested:
        return _result(
            record,
            RULE_FRESHNESS_TARGET_AGREEMENT,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            f"target_date == {requested}",
            str(record_target),
            "record target_date does not agree with the requested target_date.",
        )
    return _result(
        record,
        RULE_FRESHNESS_TARGET_AGREEMENT,
        ValidationClass.FRESHNESS_LOOKAHEAD,
        ValidationStatus.PASS,
        f"target_date == {requested}",
        str(record_target),
        "target_date agrees with the requested date.",
    )


def check_freshness_lookahead(record: EvidenceRecord, policy: MarketPolicy) -> ValidationResult:
    """Freshness and look-ahead for one record (look-ahead finding wins).

    Malformed dates fail closed (never silently acceptable). A missing date is
    handled by completeness; here a present-but-unparseable date raises FAIL.
    """
    if _is_malformed_date(record.observed_at):
        return _result(
            record,
            RULE_FRESHNESS_MALFORMED_DATE,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            "a valid observed_at date",
            repr(record.observed_at),
            "Malformed observed_at must not be accepted.",
        )
    if _is_malformed_date(record.target_date):
        return _result(
            record,
            RULE_FRESHNESS_MALFORMED_DATE,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            "a valid target_date date",
            repr(record.target_date),
            "Malformed target_date must not be accepted.",
        )
    observed = to_date(record.observed_at)
    target = to_date(record.target_date)
    if observed is None or target is None:
        return _result(
            record,
            RULE_FRESHNESS_LOOKAHEAD,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.NOT_APPLICABLE,
            "observed_at and target_date present",
            f"observed_at={record.observed_at!r}, target_date={record.target_date!r}",
            "Cannot check freshness without both dates.",
        )

    tolerance = policy.look_ahead_tolerance_days
    lookahead_days = (observed - target).days
    if lookahead_days > tolerance:
        return _result(
            record,
            RULE_FRESHNESS_LOOKAHEAD,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            f"observed_at <= target_date + {tolerance}d",
            f"observed {lookahead_days}d after target",
            "observed_at is after target_date (look-ahead).",
        )

    age = count_business_days(observed, target)
    if age > policy.freshness_width:
        return _result(
            record,
            RULE_FRESHNESS_STALE,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.FAIL,
            f"business-day age <= {policy.freshness_width}",
            f"{age} business days",
            "Stale: freshness age exceeds policy width.",
        )
    return _result(
        record,
        RULE_FRESHNESS_STALE,
        ValidationClass.FRESHNESS_LOOKAHEAD,
        ValidationStatus.PASS,
        f"business-day age <= {policy.freshness_width}",
        f"{age} business days",
        "Fresh and no look-ahead.",
    )


def check_format_numeric(record: EvidenceRecord) -> ValidationResult:
    """Numeric legality for one record: finite positive OHLC / nonnegative volume."""
    metric = record.metric_name
    value = record.value_normalized
    if value is None:
        return _result(
            record,
            RULE_FORMAT_NUMERIC,
            ValidationClass.FORMAT_NUMERIC,
            ValidationStatus.FAIL,
            "a finite numeric value",
            record.value_raw,
            "Non-numeric or missing value.",
        )
    if not value.is_finite():
        return _result(
            record,
            RULE_FORMAT_NUMERIC,
            ValidationClass.FORMAT_NUMERIC,
            ValidationStatus.FAIL,
            "finite value",
            str(value),
            "Non-finite (NaN/inf) value.",
        )
    if metric == _VOLUME_METRIC:
        if value < 0:
            return _result(
                record,
                RULE_FORMAT_NUMERIC,
                ValidationClass.FORMAT_NUMERIC,
                ValidationStatus.FAIL,
                "volume >= 0",
                str(value),
                "Negative volume.",
            )
        return _result(
            record,
            RULE_FORMAT_NUMERIC,
            ValidationClass.FORMAT_NUMERIC,
            ValidationStatus.PASS,
            "volume >= 0",
            str(value),
            "Volume is nonnegative.",
        )
    if metric in _PRICE_METRICS:
        if value <= 0:
            return _result(
                record,
                RULE_FORMAT_NUMERIC,
                ValidationClass.FORMAT_NUMERIC,
                ValidationStatus.FAIL,
                "OHLC value > 0",
                str(value),
                "Non-positive OHLC value.",
            )
        return _result(
            record,
            RULE_FORMAT_NUMERIC,
            ValidationClass.FORMAT_NUMERIC,
            ValidationStatus.PASS,
            "OHLC value > 0",
            str(value),
            "OHLC value is finite and positive.",
        )
    return _result(
        record,
        RULE_FORMAT_NUMERIC,
        ValidationClass.FORMAT_NUMERIC,
        ValidationStatus.NOT_APPLICABLE,
        "supported market metric",
        metric,
        "Unknown metric; numeric legality not applicable.",
    )


def check_asset_applicability(
    record: EvidenceRecord, expected_symbol: str, expected_asset_type: str
) -> ValidationResult:
    """Asset applicability: ticker and asset type match the expected instrument."""
    if record.ticker_normalized.upper() != expected_symbol.upper():
        return _result(
            record,
            RULE_ASSET_TICKER,
            ValidationClass.ASSET_APPLICABILITY,
            ValidationStatus.FAIL,
            expected_symbol.upper(),
            record.ticker_normalized,
            "Ticker mismatch.",
        )
    if record.asset_type != expected_asset_type:
        return _result(
            record,
            RULE_ASSET_TYPE,
            ValidationClass.ASSET_APPLICABILITY,
            ValidationStatus.FAIL,
            expected_asset_type,
            record.asset_type,
            "Asset type mismatch.",
        )
    return _result(
        record,
        RULE_ASSET_TICKER,
        ValidationClass.ASSET_APPLICABILITY,
        ValidationStatus.PASS,
        f"{expected_symbol.upper()} / {expected_asset_type}",
        f"{record.ticker_normalized.upper()} / {record.asset_type}",
        "Ticker and asset type match.",
    )


# ---------------------------------------------------------------------------
# OHLC relationship — isolated per row
# ---------------------------------------------------------------------------


def _row_key(record: EvidenceRecord) -> tuple:
    """Isolation key: (ticker_normalized, source_name, observed_at, unit_normalized).

    OHLC relationships are validated separately per row; values from different
    sources, tickers, dates, or units are never merged.
    """
    return (
        record.ticker_normalized,
        record.source_name,
        record.observed_at,
        record.unit_normalized,
    )


def _stable_sort_key(key: tuple) -> tuple:
    """A total-order sort key that is None-safe and deterministic.

    Grouping keys include date/unit components that may be ``None`` for a
    record missing a field; sorting those directly would raise
    ``TypeError``. Coercing each component to a string (``None`` -> ``""``)
    gives a reproducible, crash-free order while preserving determinism.
    """
    return tuple(("" if component is None else str(component)) for component in key)


def _cross_key(record: EvidenceRecord) -> tuple:
    """Cross-source grouping key: (ticker_normalized, metric_name, observed_at,
    unit_normalized). A comparison is only meaningful within one such group."""
    return (
        record.ticker_normalized,
        record.metric_name,
        record.observed_at,
        record.unit_normalized,
    )


def _credible_sources(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """One representative per independent source, order-stable, real values only."""
    by_source: dict[str, EvidenceRecord] = {}
    for record in records:
        if is_sentinel(record) or record.value_normalized is None:
            continue
        by_source.setdefault(record.source_name, record)
    return sorted(by_source.values(), key=lambda r: r.source_name)


def _ohlc_relationship_for_row(row_records: list[EvidenceRecord]) -> list[ValidationResult]:
    """Validate OHLC ordering for ONE isolated row.

    ``High >= max(Open, Close) >= min(Open, Close) >= Low``. Emits a result for
    every present price record so each carries its own ``evidence_id``.
    """
    prices: dict[str, EvidenceRecord] = {}
    for record in row_records:
        if record.metric_name in _PRICE_METRICS:
            prices[record.metric_name] = record

    if not prices:
        return []

    def fail_for(metric: str, expected: str, actual: str, message: str) -> ValidationResult:
        target = prices[metric] if metric in prices else next(iter(prices.values()))
        return _result(
            target,
            RULE_FORMAT_OHLC,
            ValidationClass.FORMAT_NUMERIC,
            ValidationStatus.FAIL,
            expected,
            actual,
            message,
        )

    # Some price metrics absent: the absent metric is itself a failure, and the
    # present metrics cannot be compared (the relationship cannot be confirmed),
    # so they get NOT_APPLICABLE rather than a cascading FAIL that would wrongly
    # block a present critical metric.
    if any(m not in prices for m in _PRICE_METRICS):
        results: list[ValidationResult] = []
        for m in _PRICE_METRICS:
            if m not in prices:
                results.append(
                    fail_for(m, "open, high, low, close present", f"missing {m}",
                             "Cannot validate OHLC relationships: a price metric is missing.")
                )
            else:
                results.append(
                    _result(
                        prices[m],
                        RULE_FORMAT_OHLC,
                        ValidationClass.FORMAT_NUMERIC,
                        ValidationStatus.NOT_APPLICABLE,
                        "open, high, low, close present",
                        "incomplete row",
                        "OHLC relationship not confirmable: row is incomplete.",
                    )
                )
        return results

    values = {
        m: prices[m].value_normalized
        for m in _PRICE_METRICS
        if prices[m].value_normalized is not None
    }
    if len(values) != len(_PRICE_METRICS):
        # A present metric is non-numeric: it fails; the numeric ones cannot be
        # compared (NOT_APPLICABLE) so a missing value does not cascade Block.
        results = []
        for m in _PRICE_METRICS:
            if m not in values:
                results.append(
                    fail_for(m, "numeric open/high/low/close", "non-numeric",
                             "OHLC relationship requires numeric open/high/low/close.")
                )
            else:
                results.append(
                    _result(
                        prices[m],
                        RULE_FORMAT_OHLC,
                        ValidationClass.FORMAT_NUMERIC,
                        ValidationStatus.NOT_APPLICABLE,
                        "numeric open/high/low/close",
                        "non-numeric sibling",
                        "OHLC relationship not confirmable: a sibling is non-numeric.",
                    )
                )
        return results

    open_v = values["open"]
    high_v = values["high"]
    low_v = values["low"]
    close_v = values["close"]
    mid_high = max(open_v, close_v)
    mid_low = min(open_v, close_v)
    ok = high_v >= mid_high and low_v <= mid_low and high_v >= low_v
    desc = f"O={open_v}, H={high_v}, L={low_v}, C={close_v}"
    status = ValidationStatus.PASS if ok else ValidationStatus.FAIL
    message = "OHLC relationships hold." if ok else "OHLC relationships violated."
    return [
        _result(
            prices[m],
            RULE_FORMAT_OHLC,
            ValidationClass.FORMAT_NUMERIC,
            status,
            "High >= max(Open, Close) >= min(Open, Close) >= Low",
            desc,
            message,
        )
        for m in _PRICE_METRICS
    ]


def ohlc_relationship_results(records: list[EvidenceRecord]) -> list[ValidationResult]:
    """Validate OHLC relationships separately for each isolated row.

    Rows are grouped by ``(ticker_normalized, source_name, observed_at,
    unit_normalized)`` so values from different sources are never merged. Every
    price record receives its own row relationship result.
    """
    rows: dict[tuple, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        rows[_row_key(record)].append(record)

    results: list[ValidationResult] = []
    for key in sorted(rows, key=_stable_sort_key):
        for result in _ohlc_relationship_for_row(rows[key]):
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# Cross-source consistency
# ---------------------------------------------------------------------------


def _reference_value(source_records: list[EvidenceRecord]) -> Decimal | None:
    """Deterministic median reference for 3+ sources, computed in ``Decimal``.

    The value is computed solely from finite :class:`~decimal.Decimal` inputs —
    never via ``float`` — so high-precision values are not lossy:
    odd count -> the middle ``Decimal``;
    even count -> the arithmetic mean of the two middle ``Decimal`` values.

    Exactly-two-source symmetry is handled by
    :func:`_two_source_symmetric_deviation`; this function still returns the
    correct median for a two-element input for compatibility.
    """
    values = [r.value_normalized for r in source_records]
    finite = sorted(v for v in values if v is not None and v.is_finite())
    if not finite:
        return None
    middle = len(finite) // 2
    if len(finite) % 2 == 1:
        return finite[middle]
    return (finite[middle - 1] + finite[middle]) / Decimal("2")


def _two_source_symmetric_deviation(
    a: Decimal, b: Decimal
) -> tuple[Decimal | None, bool]:
    """Symmetric percent difference for exactly two independent sources.

    Returns ``(deviation, zero_midpoint_fail)``. The same symmetric deviation is
    assigned to both credible records so the spread is not halved:

    - identical values (including two zeros) -> deviation ``0``;
    - unequal values with a zero midpoint (``a + b == 0``) -> ``(None, True)``,
      which the caller must turn into FAIL (fail closed);
    - otherwise -> ``abs(a - b) / abs((a + b) / 2)``, quantized to 4 dp.
    """
    if a == b:
        return Decimal("0"), False
    midpoint = (a + b) / Decimal("2")
    if midpoint == 0:
        return None, True
    return (abs(a - b) / abs(midpoint)).quantize(Decimal("0.0001")), False


def cross_source_consistency_results(
    records: list[EvidenceRecord], policy: MarketPolicy
) -> list[ValidationResult]:
    """Cross-source consistency, order-independent, one result per record.

    Groups by ``(ticker_normalized, metric_name, observed_at, unit_normalized)``.
    For each group:

    - fewer than two credible sources -> NOT_APPLICABLE for the whole group;
    - exactly two credible sources -> the standard symmetric percent difference
      ``abs(a - b) / abs((a + b) / 2)`` is computed **once** and that SAME
      deviation/status is assigned to both credible records (so the spread is
      not halved). Two identical zero values PASS; unequal values with a zero
      midpoint FAIL (fail closed). A non-credible sibling remains NOT_APPLICABLE.
    - three or more sources -> every record is compared against the Decimal-only
      median reference (retaining every outlier): PASS within the per-metric
      normal tolerance, WARNING above normal and below severe, FAIL at or above
      the severe tolerance.

    Every input record receives exactly one result. Results never depend on
    input order.
    """
    by_key: dict[tuple, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        by_key[_cross_key(record)].append(record)

    results: list[ValidationResult] = []
    for key in sorted(by_key, key=_stable_sort_key):
        group = by_key[key]
        credible = _credible_sources(group)
        if len(credible) < 2:
            for record in group:
                results.append(
                    _result(
                        record,
                        RULE_CROSS_SOURCE,
                        ValidationClass.CROSS_SOURCE_CONSISTENCY,
                        ValidationStatus.NOT_APPLICABLE,
                        ">= 2 independent sources",
                        f"{len(credible)} independent source(s)",
                        "Not enough independent sources to cross-check.",
                    )
                )
            continue

        # Exactly two independent sources: compute the standard symmetric percent
        # difference once and assign that SAME deviation/status to both credible
        # records. Comparing each value to the midpoint would halve the spread.
        if len(credible) == 2:
            symmetric_dev, zero_midpoint_fail = _two_source_symmetric_deviation(
                credible[0].value_normalized, credible[1].value_normalized
            )
            tolerance = policy.tolerance_for(key[1])
            if zero_midpoint_fail:
                symmetric_status = ValidationStatus.FAIL
                symmetric_message = (
                    "Zero midpoint with unequal values; not comparable (fail closed)."
                )
            elif symmetric_dev >= tolerance.severe_conflict_fraction:
                symmetric_status = ValidationStatus.FAIL
                symmetric_message = (
                    "Severe cross-source conflict at or above severe tolerance."
                )
            elif symmetric_dev > tolerance.normal_conflict_fraction:
                symmetric_status = ValidationStatus.WARNING
                symmetric_message = (
                    "Material cross-source inconsistency (above normal)."
                )
            else:
                symmetric_status = ValidationStatus.PASS
                symmetric_message = "Cross-source consistent within normal tolerance."

            credible_ids = {credible[0].evidence_id, credible[1].evidence_id}
            for record in group:
                if record.evidence_id not in credible_ids:
                    results.append(
                        _result(
                            record,
                            RULE_CROSS_SOURCE,
                            ValidationClass.CROSS_SOURCE_CONSISTENCY,
                            ValidationStatus.NOT_APPLICABLE,
                            "a numeric value for comparison",
                            repr(record.value_raw),
                            "Record has no numeric value to compare.",
                        )
                    )
                    continue
                results.append(
                    _result(
                        record,
                        RULE_CROSS_SOURCE,
                        ValidationClass.CROSS_SOURCE_CONSISTENCY,
                        symmetric_status,
                        f"deviation <= normal {tolerance.normal_conflict_fraction} to pass",
                        "zero midpoint (unequal values)" if zero_midpoint_fail else str(symmetric_dev),
                        symmetric_message,
                    )
                )
            continue

        reference = _reference_value(credible)
        tolerance: MetricTolerance = policy.tolerance_for(key[1])
        for record in group:
            # A credible reference is required; if it cannot be formed we fail
            # closed rather than silently passing.
            if reference is None:
                results.append(
                    _result(
                        record,
                        RULE_CROSS_SOURCE,
                        ValidationClass.CROSS_SOURCE_CONSISTENCY,
                        ValidationStatus.FAIL,
                        "a computable reference value",
                        "non-finite/zero reference",
                        "Cannot compute a cross-source reference.",
                    )
                )
                continue
            dev = _rel_deviation(record.value_normalized, reference, reference)
            if dev is None:
                # A non-credible record in an otherwise consistent group: it
                # cannot be compared, so it is not PASSed.
                results.append(
                    _result(
                        record,
                        RULE_CROSS_SOURCE,
                        ValidationClass.CROSS_SOURCE_CONSISTENCY,
                        ValidationStatus.NOT_APPLICABLE,
                        "a numeric value for comparison",
                        repr(record.value_raw),
                        "Record has no numeric value to compare.",
                    )
                )
                continue
            if dev >= tolerance.severe_conflict_fraction:
                status = ValidationStatus.FAIL
                message = "Severe cross-source conflict at or above severe tolerance."
            elif dev > tolerance.normal_conflict_fraction:
                status = ValidationStatus.WARNING
                message = "Material cross-source inconsistency (above normal)."
            else:
                status = ValidationStatus.PASS
                message = "Cross-source consistent within normal tolerance."
            results.append(
                _result(
                    record,
                    RULE_CROSS_SOURCE,
                    ValidationClass.CROSS_SOURCE_CONSISTENCY,
                    status,
                    f"deviation <= normal {tolerance.normal_conflict_fraction} to pass",
                    str(dev),
                    message,
                )
            )
    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_market_records(
    records: list[EvidenceRecord],
    *,
    expected_symbol: str,
    target_date: str,
    expected_asset_type: str = "stock",
    policy: MarketPolicy | None = None,
) -> dict[str, list[ValidationResult]]:
    """Validate market records against all five classes.

    Args:
        records: Market OHLCV ``EvidenceRecord`` objects (may span multiple
            independent sources for cross-source consistency).
        expected_symbol: The normalized ticker the evidence must match.
        target_date: The requested analysis date (``YYYY-MM-DD``); every record's
            ``target_date`` must agree with it.
        expected_asset_type: Expected asset type (default ``stock``).
        policy: Deterministic policy thresholds.

    Returns:
        A dict mapping ``evidence_id`` -> list of ``ValidationResult`` for that
        record, covering the per-record completeness/freshness/format/asset
        checks plus the isolated OHLC-relationship and cross-source checks.
        The listed results are sorted for determinism.
    """
    policy = policy or MarketPolicy()
    grouped: dict[str, list[ValidationResult]] = defaultdict(list)

    for record in records:
        grouped[record.evidence_id].append(check_completeness(record))
        grouped[record.evidence_id].append(
            check_target_date_agreement(record, target_date)
        )
        grouped[record.evidence_id].append(check_freshness_lookahead(record, policy))
        grouped[record.evidence_id].append(check_format_numeric(record))
        grouped[record.evidence_id].append(
            check_asset_applicability(record, expected_symbol, expected_asset_type)
        )

    for result in ohlc_relationship_results(records):
        grouped[result.evidence_id].append(result)

    for result in cross_source_consistency_results(records, policy):
        grouped[result.evidence_id].append(result)

    return {k: sorted(v, key=lambda r: r.rule_id) for k, v in grouped.items()}
