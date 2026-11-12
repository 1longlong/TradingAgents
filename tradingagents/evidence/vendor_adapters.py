"""Honest vendor-origin adapters for optional-category (non-market) evidence.

This module turns *source-origin* vendor records — the same typed objects the
dataflow functions fetch before they format a public prose string — into
:class:`~tradingagents.evidence.models.EvidenceRecord` objects plus per-record
:class:`~tradingagents.evidence.models.ValidationResult`s and a
:class:`~tradingagents.evidence.models.SourceAttempt`.

Design rules (authoritative, see ADR-008):

- **Truthful.** Only the vendor's own structured fields are used. It never
  parses analyst prose, never reads a Markdown renderer, and never invents a
  source date, url, unit or sentiment label. A vendor return with no usable
  structure is recorded as ``unsupported``/``malformed``/``unavailable`` — never
  as a high grade.
- **Per-category validation.** Each category has its own deterministic checks;
  the market OHLCV numeric schema is never forced onto qualitative news or
  sentiment rows.
- **Point in time.** Fundamentals require a filed/available-by date; a fiscal
  period end is not availability. News requires a published date. An item dated
  after the target date is excluded, never decisive. A missing publication date
  is not assumed equal to the target/retrieval time.
- **Lineage + dedup.** Every record names the provider and a content identity
  (article key, filing accession-dependent key, post identity). Syndicated /
  duplicate items collapse to one identity so an independent-source count is
  not inflated.
- **Deterministic IDs.** ``<run_id>/<category>/<source>/<slug>/<index>`` where the
  slug is a stable hash of the content identity and the index is a stable
  sequence position — never a wall-clock value.

The adapters are pure functions; the capture side effect (into the run-scoped
collector) is a separate, explicit step performed by the dataflow call sites.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from tradingagents.evidence.models import (
    Criticality,
    EvidenceRecord,
    QualityStatus,
    SourceAttempt,
    SourceResultStatus,
    ValidationClass,
    ValidationResult,
    ValidationStatus,
)
from tradingagents.evidence.origin import (
    BASIS_FILED,
    BASIS_PERIOD_END,
    BASIS_PUBLISHED,
    BASIS_UNKNOWN,
    SCALE_BASE,
    OriginMetadata,
)
from tradingagents.evidence.policy import (
    CATEGORY_FUNDAMENTALS,
    CATEGORY_NEWS,
    CATEGORY_SENTIMENT,
    to_date,
)

# Sentinel content that must never count as evidence (mirrors the market raw
# sentinels). A captured row whose text is one of these is refused.
_OPTIONAL_SENTINELS = frozenset({"NO_DATA_AVAILABLE", "DATA_UNAVAILABLE"})

# Deterministic rule ids for the optional-category validation classes.
RULE_COMPLETENESS = "optional.completeness.required_fields"
RULE_SENTINEL = "optional.completeness.sentinel"
RULE_PUBLICATION_DATE = "optional.freshness.publication_date"
RULE_MALFORMED_DATE = "optional.freshness.malformed_date"
RULE_LOOKAHEAD = "optional.freshness.lookahead"
RULE_FILED_ASOF = "optional.fundamentals.filed_as_of"
RULE_AMOUNT_FORMAT = "optional.fundamentals.amount_format"
RULE_ASSET_TICKER = "optional.asset.ticker_match"
RULE_LINEAGE = "optional.consistency.lineage_key"

# Amount-like fundamentals metric ids (must carry a finite numeric magnitude).
# Non-amount (text) fundamental facts use a separate schema.
_AMOUNT_METRICS: frozenset[str] = frozenset(
    {
        "revenue",
        "net_income",
        "total_assets",
        "total_liabilities",
        "stockholders_equity",
        "operating_cash_flow",
        "totalrevenue",
        "netincome",
        "totalassets",
        "totalliabilities",
        "totalshareholderequity",
        "operatingcashflow",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(*parts: str) -> str:
    """Deterministic short hash of the content identity of a record.

    Called with a single lineage-key argument; the join keeps the helper
    general if additional identity components are ever needed.
    """
    joined = "\u0001".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _parse_date(value: Any) -> date | None:
    return to_date(value)


def _iso_date(value: Any) -> str | None:
    """Best-effort ``YYYY-MM-DD`` for a vendor date; ``None`` when absent/bad.

    Only a real ``str``/``datetime``/``date`` is accepted. A bare integer epoch
    or an ``int`` like ``20260510`` is NOT a vendor date string and is rejected
    (``None``) rather than silently parsed as a calendar date — the validator
    then fails the record closed instead of trusting an ambiguous type.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, datetime, date)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    parsed = to_date(value)
    return parsed.isoformat() if parsed is not None else None


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm_url(value: Any) -> str:
    """Strip query strings/usernames so a URL cannot leak a token or identity."""
    text = _norm_text(value)
    if not text:
        return ""
    # Drop query/fragment (may carry tokens) and any userinfo@host prefix.
    return text.split("?", 1)[0].split("#", 1)[0].split("@")[-1]


def make_optional_evidence_id(
    run_id: str,
    category: str,
    source_name: str,
    lineage_key: str,
    index: int,
) -> str:
    """Stable deterministic evidence id for an optional-category record.

    The index is a stable positional component and must be deterministic for a
    given lineage key (a content-hash record uses ``0``; a set of records with
    no content identity uses its sorted position). Never a wall-clock value.
    """
    return "/".join(
        [str(run_id), str(category), str(source_name), _slug(lineage_key), str(int(index))]
    )


# ---------------------------------------------------------------------------
# Validation results
# ---------------------------------------------------------------------------


def _result(
    evidence_id: str,
    rule_id: str,
    validation_class: ValidationClass,
    status: ValidationStatus,
    expected: Any,
    actual: Any,
    message: str,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        validation_class=validation_class,
        status=status,
        expected=expected,
        actual=actual,
        message=message,
        evidence_id=evidence_id,
    )


def _completeness(record: EvidenceRecord, required_text: tuple[str, ...]) -> ValidationResult:
    if (record.value_raw or "").strip().upper() in _OPTIONAL_SENTINELS:
        return _result(
            record.evidence_id,
            RULE_SENTINEL,
            ValidationClass.COMPLETENESS,
            ValidationStatus.FAIL,
            "a real value",
            record.value_raw,
            "Sentinel data marker must not count as evidence.",
        )
    missing: list[str] = []
    if not (record.ticker_normalized or "").strip():
        missing.append("ticker_normalized")
    if not (record.category or "").strip():
        missing.append("category")
    if not (record.metric_name or "").strip():
        missing.append("metric_name")
    if not (record.source_name or "").strip():
        missing.append("source_name")
    if not (record.value_raw or "").strip():
        missing.append("value_raw")
    for field_name in required_text:
        if not str(getattr(record, field_name, "") or "").strip():
            missing.append(field_name)
    if missing:
        return _result(
            record.evidence_id,
            RULE_COMPLETENESS,
            ValidationClass.COMPLETENESS,
            ValidationStatus.FAIL,
            "all required fields present",
            ", ".join(missing),
            f"Missing required field(s): {', '.join(missing)}.",
        )
    return _result(
        record.evidence_id,
        RULE_COMPLETENESS,
        ValidationClass.COMPLETENESS,
        ValidationStatus.PASS,
        "all required fields present",
        "present",
        "All required fields present.",
    )


def _asset_match(record: EvidenceRecord, expected_symbol: str) -> ValidationResult:
    if record.ticker_normalized.upper() != (expected_symbol or "").upper():
        return _result(
            record.evidence_id,
            RULE_ASSET_TICKER,
            ValidationClass.ASSET_APPLICABILITY,
            ValidationStatus.FAIL,
            (expected_symbol or "").upper(),
            record.ticker_normalized,
            "Ticker mismatch.",
        )
    return _result(
        record.evidence_id,
        RULE_ASSET_TICKER,
        ValidationClass.ASSET_APPLICABILITY,
        ValidationStatus.PASS,
        (expected_symbol or "").upper(),
        record.ticker_normalized.upper(),
        "Ticker matches.",
    )


def _publication_vs_target(
    record: EvidenceRecord,
    target_date: str,
) -> tuple[list[ValidationResult], str | None]:
    """Validate a published/filed date against the target date.

    Returns ``(results, exclusion_reason)``. ``exclusion_reason`` is a stable
    code (``malformed_date``/``lookahead``) when the record must be excluded, or
    ``None`` when it is on-or-before the target.
    """
    results: list[ValidationResult] = []
    published_raw = record.observed_at
    if not (published_raw or "").strip():
        # Missing publication date: cannot be assumed to be the target/retrieval
        # time. Fail closed (record not decisive).
        results.append(
            _result(
                record.evidence_id,
                RULE_PUBLICATION_DATE,
                ValidationClass.FRESHNESS_LOOKAHEAD,
                ValidationStatus.FAIL,
                "a known published/filed date",
                repr(published_raw),
                "Publication date is unknown; not assumed equal to the target date.",
            )
        )
        return results, "missing_date"
    published = _parse_date(published_raw)
    target = _parse_date(target_date)
    if published is None:
        results.append(
            _result(
                record.evidence_id,
                RULE_MALFORMED_DATE,
                ValidationClass.FRESHNESS_LOOKAHEAD,
                ValidationStatus.FAIL,
                "a valid published/filed date",
                repr(published_raw),
                "Malformed publication/filing date must not be accepted.",
            )
        )
        return results, "malformed_date"
    if target is None:
        results.append(
            _result(
                record.evidence_id,
                RULE_PUBLICATION_DATE,
                ValidationClass.FRESHNESS_LOOKAHEAD,
                ValidationStatus.FAIL,
                "a valid requested target date",
                repr(target_date),
                "Requested target date is malformed; cannot validate publication.",
            )
        )
        return results, "malformed_date"
    if published > target:
        results.append(
            _result(
                record.evidence_id,
                RULE_LOOKAHEAD,
                ValidationClass.FRESHNESS_LOOKAHEAD,
                ValidationStatus.FAIL,
                f"published <= {target.isoformat()}",
                published.isoformat(),
                "Published/filed after the target date (look-ahead); excluded.",
            )
        )
        return results, "lookahead"
    results.append(
        _result(
            record.evidence_id,
            RULE_PUBLICATION_DATE,
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationStatus.PASS,
            f"published <= {target.isoformat()}",
            published.isoformat(),
            "Published/filed on or before the target date.",
        )
    )
    return results, None


# ---------------------------------------------------------------------------
# Category validators
# ---------------------------------------------------------------------------


def validate_fundamentals_record(
    record: EvidenceRecord,
    *,
    expected_symbol: str,
    target_date: str,
) -> tuple[list[ValidationResult], str | None]:
    """Validate one fundamentals record.

    Amount-like metrics (revenue, net income, total assets, ...) MUST carry a
    finite numeric magnitude; a missing/NaN/bool/unparseable amount is a FAIL,
    not NOT_APPLICABLE. A genuinely text fact (e.g. a company name metric) is a
    separate schema and the amount check is NOT_APPLICABLE there.
    """
    results = [
        _completeness(record, ("observed_at",)),
        _asset_match(record, expected_symbol),
    ]
    date_results, exclusion = _publication_vs_target(record, target_date)
    results.extend(date_results)
    if exclusion is None:
        amount_like = record.metric_name.lower() in _AMOUNT_METRICS
        if amount_like:
            # Amount must be a finite numeric magnitude. ``value_normalized`` is
            # already ``None`` for a bool/NaN/inf/unparseable input (quantized at
            # construction), so a None here is a real amount failure.
            if record.value_normalized is None or not record.value_normalized.is_finite():
                results.append(
                    _result(
                        record.evidence_id,
                        RULE_AMOUNT_FORMAT,
                        ValidationClass.FORMAT_NUMERIC,
                        ValidationStatus.FAIL,
                        "a finite numeric amount",
                        record.value_raw,
                        "Amount-like metric has no finite numeric magnitude.",
                    )
                )
            else:
                results.append(
                    _result(
                        record.evidence_id,
                        RULE_AMOUNT_FORMAT,
                        ValidationClass.FORMAT_NUMERIC,
                        ValidationStatus.PASS,
                        "a finite numeric amount",
                        str(record.value_normalized),
                        "Finite amount.",
                    )
                )
        else:
            # A non-amount (text) fundamental fact uses a different schema; the
            # numeric amount check does not apply.
            results.append(
                _result(
                    record.evidence_id,
                    RULE_AMOUNT_FORMAT,
                    ValidationClass.FORMAT_NUMERIC,
                    ValidationStatus.NOT_APPLICABLE,
                    "a finite amount",
                    record.value_raw,
                    "Non-amount (text) fact; amount format check not applicable.",
                )
            )
    return results, exclusion


def validate_news_record(
    record: EvidenceRecord,
    *,
    expected_symbol: str,
    target_date: str,
) -> tuple[list[ValidationResult], str | None]:
    """Validate one news record; a published date is required, no numeric schema."""
    results = [
        _completeness(record, ("observed_at",)),
        _asset_match(record, expected_symbol),
    ]
    date_results, exclusion = _publication_vs_target(record, target_date)
    results.extend(date_results)
    return results, exclusion


def validate_sentiment_record(
    record: EvidenceRecord,
    *,
    expected_symbol: str,
    target_date: str,
) -> tuple[list[ValidationResult], str | None]:
    """Validate one sentiment record; source-native label, no invented sentiment."""
    results = [
        _completeness(record, ("observed_at",)),
        _asset_match(record, expected_symbol),
    ]
    date_results, exclusion = _publication_vs_target(record, target_date)
    results.extend(date_results)
    return results, exclusion


_CATEGORY_VALIDATORS = {
    CATEGORY_FUNDAMENTALS: validate_fundamentals_record,
    CATEGORY_NEWS: validate_news_record,
    CATEGORY_SENTIMENT: validate_sentiment_record,
}


def validate_optional_records(
    records_by_category: dict[str, list[EvidenceRecord]],
    *,
    expected_symbol: str,
    target_date: str,
) -> dict[str, list[ValidationResult]]:
    """Validate captured optional records per category.

    Returns ``evidence_id -> [ValidationResult, ...]`` (deterministically
    ordered by rule id) for every record supplied. Unknown categories never
    validate (they are silently ignored, never graded).
    """
    out: dict[str, list[ValidationResult]] = {}
    for category, records in records_by_category.items():
        validator = _CATEGORY_VALIDATORS.get(category)
        if validator is None:
            continue
        for record in records:
            results, _exclusion = validator(
                record, expected_symbol=expected_symbol, target_date=target_date
            )
            out[record.evidence_id] = sorted(results, key=lambda r: r.rule_id)
    return out


# ---------------------------------------------------------------------------
# Record builders — fundamentals
# ---------------------------------------------------------------------------


def _fundamentals_criticality(metric_name: str) -> Criticality:
    """No optional fundamentals metric is critical to the overall decision."""
    return Criticality.IMPORTANT if metric_name in ("revenue", "net_income") else Criticality.SUPPORTING


def build_sec_fundamentals_record(
    *,
    run_id: str,
    symbol_input: str,
    symbol_normalized: str,
    target_date: str,
    metric_name: str,
    value_raw: str,
    value_normalized: Decimal | None,
    unit_raw: str,
    filed_date: str,
    period_end: str,
    source_ref: str,
    fetched_at: str | None = None,
) -> EvidenceRecord:
    """Build one fundamentals record from an SEC company-facts row.

    ``observed_at`` is the **filed** date (when the fact became public), never the
    fiscal period end. ``source_ref`` carries the lineage (tag + accession).
    """
    lineage_key = f"sec|{source_ref}|{metric_name}|{period_end}|{filed_date}"
    evidence_id = make_optional_evidence_id(
        run_id, CATEGORY_FUNDAMENTALS, "sec_edgar", lineage_key, 0
    )
    return EvidenceRecord.build(
        evidence_id=evidence_id,
        run_id=run_id,
        ticker_input=str(symbol_input),
        ticker_normalized=symbol_normalized.upper(),
        asset_type="stock",
        category=CATEGORY_FUNDAMENTALS,
        metric_name=metric_name,
        value_raw=value_raw,
        value_normalized=value_normalized,
        unit_raw=unit_raw,
        unit_normalized=unit_raw,
        source_name="sec_edgar",
        source_ref=source_ref,
        observed_at=_iso_date(filed_date),
        fetched_at=fetched_at or _now_iso(),
        target_date=_iso_date(target_date),
        criticality=_fundamentals_criticality(metric_name),
        validation_results=[],
        quality_status=QualityStatus.LOW,
        quality_reasons=["unvalidated"],
    )


def build_alpha_vantage_fundamentals_record(
    *,
    run_id: str,
    symbol_input: str,
    symbol_normalized: str,
    target_date: str,
    metric_name: str,
    value_raw: str,
    value_normalized: Decimal | None,
    unit_raw: str,
    fiscal_period_end: str,
    source_ref: str,
    fetched_at: str | None = None,
) -> EvidenceRecord:
    """Build one fundamentals record from Alpha Vantage statement JSON.

    Alpha Vantage statement rows carry a fiscal period end but **no filing
    date**. The fiscal-end date is therefore recorded only as ``source_ref``
    context, and ``observed_at`` stays ``None`` so the per-record validator
    fails it closed (a period end is not availability) instead of assuming the
    fact was public by the target date.
    """
    lineage_key = f"alpha_vantage|{source_ref}|{metric_name}|{fiscal_period_end}"
    evidence_id = make_optional_evidence_id(
        run_id, CATEGORY_FUNDAMENTALS, "alpha_vantage", lineage_key, 0
    )
    return EvidenceRecord.build(
        evidence_id=evidence_id,
        run_id=run_id,
        ticker_input=str(symbol_input),
        ticker_normalized=symbol_normalized.upper(),
        asset_type="stock",
        category=CATEGORY_FUNDAMENTALS,
        metric_name=metric_name,
        value_raw=value_raw,
        value_normalized=value_normalized,
        unit_raw=unit_raw,
        unit_normalized=unit_raw,
        source_name="alpha_vantage",
        source_ref=f"{source_ref}|fiscal_end={fiscal_period_end}",
        observed_at=None,
        fetched_at=fetched_at or _now_iso(),
        target_date=_iso_date(target_date),
        criticality=_fundamentals_criticality(metric_name),
        validation_results=[],
        quality_status=QualityStatus.LOW,
        quality_reasons=["unvalidated"],
    )


# ---------------------------------------------------------------------------
# Origin metadata builders (ADR-010): typed, distinct date roles + unit semantics
# ---------------------------------------------------------------------------


def _unit_scale(unit: str) -> tuple[Decimal | None, str, str]:
    """Split a vendor unit into ``(value_scale, unit, currency)`` honestly.

    SEC ``USD`` is one-dollar USD (base scale). A unit already carrying a currency
    (e.g. ``USD``) is money. The scale is ``SCALE_BASE`` only when the source
    unit is a recognized base unit (a currency / ``shares`` / ``percent`` / EPS);
    an unrecognized unit leaves the scale ``None`` (UNKNOWN) so the validator
    refuses to verify a magnitude rather than assuming base units.
    """
    raw = _norm_text(unit)
    upper = raw.upper()
    currency = ""
    if upper in ("USD", "EUR", "GBP", "JPY", "CNY", "HKD", "CAD", "AUD", "CHF"):
        currency = upper
    base_units = {"SHARES", "SHARE", "PERCENT", "%", "EPS", "USD/SHARES", "USD/SHARE"}
    scale: Decimal | None = SCALE_BASE if (currency or upper in base_units) else None
    return scale, raw, currency


def build_sec_origin(
    *,
    target_date: str,
    filed_date: str,
    period_end: str,
    unit: str,
    fetched_at: str | None,
) -> OriginMetadata:
    """Origin for an SEC row: genuine ``period_end`` (observation) + ``filed``."""
    scale, unit_text, currency = _unit_scale(unit)
    filed_iso = _iso_date(filed_date)
    return OriginMetadata(
        target_date=_iso_date(target_date),
        observation_date=_iso_date(period_end) if period_end else None,
        availability_date=filed_iso,
        filed_at=filed_iso,
        retrieved_at=fetched_at,
        date_basis=BASIS_FILED if filed_iso else BASIS_UNKNOWN,
        value_scale=scale,
        unit=unit_text,
        currency=currency,
        period_end_source="vendor" if period_end else "absent",
    )


def build_alpha_vantage_origin(
    *,
    target_date: str,
    fiscal_period_end: str,
    unit: str,
    fetched_at: str | None,
) -> OriginMetadata:
    """Origin for an Alpha Vantage / yfinance row: period end only, no filing date.

    Availability stays ``None`` (a fiscal period end is not availability), so the
    record remains unavailable for historical proof. The genuine fiscal period end
    is preserved as the observation date.
    """
    scale, unit_text, currency = _unit_scale(unit)
    return OriginMetadata(
        target_date=_iso_date(target_date),
        observation_date=_iso_date(fiscal_period_end) if fiscal_period_end else None,
        availability_date=None,
        filed_at=None,
        retrieved_at=fetched_at,
        date_basis=BASIS_PERIOD_END if fiscal_period_end else BASIS_UNKNOWN,
        value_scale=scale,
        unit=unit_text,
        currency=currency,
        period_end_source="vendor" if fiscal_period_end else "absent",
    )


def build_news_origin(
    *,
    target_date: str,
    published: str | None,
    fetched_at: str | None,
) -> OriginMetadata:
    """Origin for a news item: published date/instant is availability, not claim date."""
    published_iso = _iso_date(published) if published else None
    return OriginMetadata(
        target_date=_iso_date(target_date),
        observation_date=None,
        availability_date=published_iso,
        published_at=str(published) if published else None,
        retrieved_at=fetched_at,
        date_basis=BASIS_PUBLISHED if published_iso else BASIS_UNKNOWN,
        value_scale=None,
        unit="headline",
        currency="",
        period_end_source="absent",
    )


def build_sentiment_origin(
    *,
    target_date: str,
    posted_at: str | None,
    fetched_at: str | None,
) -> OriginMetadata:
    """Origin for a sentiment post: the posted instant is availability."""
    posted_iso = _iso_date(posted_at) if posted_at else None
    return OriginMetadata(
        target_date=_iso_date(target_date),
        observation_date=None,
        availability_date=posted_iso,
        published_at=str(posted_at) if posted_at else None,
        retrieved_at=fetched_at,
        date_basis=BASIS_PUBLISHED if posted_iso else BASIS_UNKNOWN,
        value_scale=None,
        unit="native_label",
        currency="",
        period_end_source="absent",
    )


# ---------------------------------------------------------------------------
# Record builders — news
# ---------------------------------------------------------------------------


def _news_lineage_key(title: str, url: str, published: str) -> str:
    """Content identity used to collapse syndicated/duplicate articles.

    Publishes under several providers syndicate the same article; the normalized
    title is the reliable identity (a URL can differ per syndicator), so the key
    is title-first with the published date as a tiebreaker. This keeps a single
    independent-source count from being inflated by the same story.
    """
    return f"news|{_norm_text(title).lower()}|{published}"


def build_news_record(
    *,
    run_id: str,
    symbol_input: str,
    symbol_normalized: str,
    target_date: str,
    title: str,
    publisher: str,
    url: str,
    published: str | None,
    source_name: str,
    fetched_at: str | None = None,
    index: int = 0,
) -> EvidenceRecord:
    """Build one news record from a vendor's original article object."""
    published_iso = _iso_date(published) if published else None
    lineage_key = _news_lineage_key(title, url, published_iso or "")
    evidence_id = make_optional_evidence_id(
        run_id, CATEGORY_NEWS, source_name, lineage_key, index
    )
    safe_url = _norm_url(url)
    return EvidenceRecord.build(
        evidence_id=evidence_id,
        run_id=run_id,
        ticker_input=str(symbol_input),
        ticker_normalized=symbol_normalized.upper(),
        asset_type="stock",
        category=CATEGORY_NEWS,
        metric_name=_norm_text(title) or "untitled",
        value_raw=_norm_text(title),
        value_normalized=None,
        unit_raw="headline",
        unit_normalized="headline",
        source_name=source_name,
        source_ref=f"{_norm_text(publisher)}|{safe_url}",
        observed_at=published_iso,
        fetched_at=fetched_at or _now_iso(),
        target_date=_iso_date(target_date),
        criticality=Criticality.SUPPORTING,
        validation_results=[],
        quality_status=QualityStatus.LOW,
        quality_reasons=["unvalidated"],
    )


# ---------------------------------------------------------------------------
# Record builders — sentiment
# ---------------------------------------------------------------------------


def build_sentiment_record(
    *,
    run_id: str,
    symbol_input: str,
    symbol_normalized: str,
    target_date: str,
    source_name: str,
    native_label: str | None,
    body: str,
    posted_at: str | None,
    author_ref: str,
    lineage_key: str,
    fetched_at: str | None = None,
    index: int = 0,
) -> EvidenceRecord:
    """Build one sentiment record from a source-native post.

    ``native_label`` is the vendor-provided label (StockTwits
    ``Bullish``/``Bearish``) or ``None`` when the source carries no native label
    (Reddit). A ``None`` label is recorded as ``unlabeled`` — an invented
    sentiment value is never assigned.
    """
    posted_iso = _iso_date(posted_at) if posted_at else None
    label = _norm_text(native_label) if native_label else ""
    label_norm = "unlabeled" if not label else label.lower()
    evidence_id = make_optional_evidence_id(
        run_id, CATEGORY_SENTIMENT, source_name, lineage_key, index
    )
    return EvidenceRecord.build(
        evidence_id=evidence_id,
        run_id=run_id,
        ticker_input=str(symbol_input),
        ticker_normalized=symbol_normalized.upper(),
        asset_type="stock",
        category=CATEGORY_SENTIMENT,
        metric_name=f"sentiment_label:{label_norm}",
        value_raw=label_norm,
        value_normalized=None,
        unit_raw="native_label",
        unit_normalized="native_label" if label else "unlabeled",
        source_name=source_name,
        source_ref=str(author_ref),
        observed_at=posted_iso,
        fetched_at=fetched_at or _now_iso(),
        target_date=_iso_date(target_date),
        criticality=Criticality.SUPPORTING,
        validation_results=[],
        quality_status=QualityStatus.LOW,
        quality_reasons=["unvalidated"],
    )


# ---------------------------------------------------------------------------
# Source-attempt helper
# ---------------------------------------------------------------------------


def make_source_attempt(
    *,
    source: str,
    tool: str,
    result_status: SourceResultStatus,
    started_at: str | None = None,
    duration: float | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> SourceAttempt:
    """Build a sanitized ``SourceAttempt`` (no URL/secret/body text in errors).

    ``error_message`` is truncated to a short, generic classification; callers
    pass only a safe category (e.g. ``"rate_limited"``), never a raw exception
    string that could carry a URL, key, or body.
    """
    safe_message = None
    if error_message:
        safe_message = re.sub(r"https?://\S+", "<url>", str(error_message))[:120]
    return SourceAttempt(
        source=str(source),
        tool=str(tool),
        started_at=started_at,
        duration=duration,
        result_status=result_status,
        error_type=error_type,
        error_message=safe_message,
    )
