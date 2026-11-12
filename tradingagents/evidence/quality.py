"""Per-record quality precedence and per-category aggregation.

This module turns a set of market :class:`~tradingagents.evidence.models.EvidenceRecord`
objects plus their :class:`~tradingagents.evidence.models.ValidationResult`s into
(1) a per-record :class:`QualityStatus` and (2) a per-category
:class:`~tradingagents.evidence.models.EvidenceGroupQuality`.

Per-record precedence (authoritative):

- **Blocked** — a critical hard failure (completeness/format/freshness-stale
  FAIL on a critical metric), a look-ahead FAIL, a ticker mismatch, a severe
  critical cross-source conflict, or missing/unusable **critical** evidence.
- **Low** — missing/unusable **important** evidence (not Blocked), a material
  noncritical (important/supporting) failure, or a non-severe warning/conflict.
- **Medium** — all hard checks pass with at least one credible source.
- **High** — never assigned at the per-record level (it is a group property).

Category aggregation (authoritative):

- **Blocked** — any record in the group is Blocked (a critical group blocked
  lands the whole gate on ``blocked``; kept fail-closed).
- **Low** — not blocked but some record is Low, or cross-source conflict.
- **Medium** — hard checks pass everywhere with at least one credible source,
  but not every critical metric is fully corroborated.
- **High** — every *critical* metric in the category has at least
  ``policy.min_independent_sources`` credible sources **and** explicit
  consistent ``PASS`` cross-source results. Merely having two different source
  names somewhere in the category is not sufficient.

This layer is pure and LLM-free; it only inspects records, results, and the
deterministic :class:`~tradingagents.evidence.policy.MarketPolicy`.
"""

from __future__ import annotations

from typing import Any, Final

from tradingagents.evidence.models import (
    Criticality,
    EvidenceGroupQuality,
    EvidenceRecord,
    QualityStatus,
    ValidationClass,
    ValidationStatus,
)
from tradingagents.evidence.policy import MarketPolicy
from tradingagents.evidence.validate import is_sentinel

# Reason codes (stable identifiers consumed by the gate and serialized).
REASON_BLOCKED_CRITICAL_FAILURE: Final[str] = "blocked_critical_failure"
REASON_BLOCKED_LOOKAHEAD: Final[str] = "blocked_lookahead"
REASON_BLOCKED_TICKER_MISMATCH: Final[str] = "blocked_ticker_mismatch"
REASON_BLOCKED_ASSET_MISMATCH: Final[str] = "blocked_asset_mismatch"
REASON_BLOCKED_SEVERE_CONFLICT: Final[str] = "blocked_severe_conflict"
REASON_BLOCKED_NO_USABLE_SOURCE: Final[str] = "blocked_no_usable_source"
REASON_LOW_MATERIAL_FAILURE: Final[str] = "low_material_failure"
REASON_HIGH: Final[str] = "high"
REASON_MEDIUM_SINGLE_SOURCE: Final[str] = "medium_single_source"
REASON_LOW_NO_SOURCE: Final[str] = "low_no_source"

_CRITICALITY_RANK = {
    Criticality.CRITICAL: 3,
    Criticality.IMPORTANT: 2,
    Criticality.SUPPORTING: 1,
}


def _highest_criticality(records: list[EvidenceRecord]) -> Criticality:
    ranks: list[int] = []
    for record in records:
        if isinstance(record.criticality, Criticality):
            ranks.append(_CRITICALITY_RANK[record.criticality])
    if not ranks:
        return Criticality.SUPPORTING
    top = max(ranks)
    return next(
        crit for crit, rank in _CRITICALITY_RANK.items() if rank == top
    )


# ---------------------------------------------------------------------------
# Per-record precedence
# ---------------------------------------------------------------------------


def evaluate_record_quality(
    record: EvidenceRecord,
    results,
    policy: MarketPolicy | None = None,
) -> tuple[QualityStatus, list[str]]:
    """Determine the per-record ``QualityStatus`` and reason codes.

    Args:
        record: One market evidence record.
        results: The ``ValidationResult`` objects for this record.
        policy: Deterministic policy (used only to consult the record's
            criticality grouping).

    Returns:
        A ``(quality_status, reason_codes)`` tuple. The stringed reason codes
        are stable and are used by the gate and serialization.
    """
    critical = record.criticality == Criticality.CRITICAL

    # Missing/unusable source: critical becomes Blocked, important becomes Low.
    if is_sentinel(record) or record.value_normalized is None:
        if critical:
            return QualityStatus.BLOCKED, [REASON_BLOCKED_NO_USABLE_SOURCE]
        return QualityStatus.LOW, [REASON_LOW_MATERIAL_FAILURE]

    blocking: list[str] = []
    low_reasons: list[str] = []
    for result in results or []:
        if result.status == ValidationStatus.FAIL:
            if result.validation_class == ValidationClass.FRESHNESS_LOOKAHEAD and (
                result.rule_id == "market.freshness.lookahead"
            ):
                # Look-ahead is a hard blocker regardless of criticality.
                blocking.append(REASON_BLOCKED_LOOKAHEAD)
            elif result.validation_class == ValidationClass.ASSET_APPLICABILITY:
                if result.rule_id == "market.asset.ticker_match":
                    # Ticker mismatch is a hard blocker regardless of criticality.
                    blocking.append(REASON_BLOCKED_TICKER_MISMATCH)
                elif result.rule_id == "market.asset.type_match":
                    blocking.append(REASON_BLOCKED_ASSET_MISMATCH)
            elif result.validation_class == ValidationClass.CROSS_SOURCE_CONSISTENCY:
                if critical:
                    blocking.append(REASON_BLOCKED_SEVERE_CONFLICT)
                else:
                    low_reasons.append(REASON_LOW_MATERIAL_FAILURE)
            elif result.validation_class == ValidationClass.COMPLETENESS or result.validation_class in (
                ValidationClass.FORMAT_NUMERIC,
                ValidationClass.FRESHNESS_LOOKAHEAD,
            ):
                if critical:
                    blocking.append(REASON_BLOCKED_CRITICAL_FAILURE)
                else:
                    low_reasons.append(REASON_LOW_MATERIAL_FAILURE)
        elif result.status == ValidationStatus.WARNING:
            low_reasons.append(REASON_LOW_MATERIAL_FAILURE)

    if blocking:
        unique = list(dict.fromkeys(blocking))
        return QualityStatus.BLOCKED, unique
    if low_reasons:
        unique = list(dict.fromkeys(low_reasons))
        return QualityStatus.LOW, unique
    return QualityStatus.MEDIUM, [REASON_MEDIUM_SINGLE_SOURCE]


# ---------------------------------------------------------------------------
# Optional-category per-record classification (never forces the OHLCV schema)
# ---------------------------------------------------------------------------

_OPTIONAL_CATEGORIES = frozenset({"fundamentals", "news", "sentiment"})

# Mandatory PASS rule ids per optional category. A record is only usable when the
# category's core checks are explicitly PRESENT and PASS — an absent/empty
# result set, or one where the mandatory checks are only NOT_APPLICABLE, must
# fail closed (never silently Medium).
_OPTIONAL_MANDATORY_RULES: dict[str, tuple[str, ...]] = {
    # completeness + a known publication/filed date (the freshness class PASS).
    "fundamentals": ("optional.completeness.required_fields", "optional.freshness.publication_date"),
    "news": ("optional.completeness.required_fields", "optional.freshness.publication_date"),
    "sentiment": ("optional.completeness.required_fields", "optional.freshness.publication_date"),
}


def evaluate_optional_record_quality(
    record: EvidenceRecord,
    results,
) -> tuple[QualityStatus, list[str]]:
    """Classify ONE optional-category record from its own validator results.

    Optional categories are qualitative: a news headline or a source-native
    sentiment label has no numeric ``value_normalized`` and must NOT be forced
    through the market rule that treats a ``None`` value as unusable. This
    classifier is driven solely by the per-record ``ValidationResult`` set the
    per-category validator produced, and **fails closed**:

    - any ``FAIL`` (completeness / look-ahead / filed-as-of / ticker / amount
      legality) -> ``Blocked`` (record not usable/decisive);
    - the category's mandatory checks must be PRESENT and ``PASS``; if any is
      absent or not PASS (e.g. an empty result set, or all NOT_APPLICABLE) ->
      ``Blocked`` (incomplete/unknown validation never becomes Medium);
    - any ``WARNING`` (with all mandatory PASS) -> ``Low``;
    - otherwise -> ``Medium``.

    A sentinel raw value is always Blocked. This never inspects numeric
    magnitudes for text facts, so a valid qualitative record is Medium and
    becomes usable, while an excluded/malformed/unvalidated record stays
    Blocked/Low.
    """
    if is_sentinel(record):
        return QualityStatus.BLOCKED, [REASON_BLOCKED_NO_USABLE_SOURCE]
    results = list(results or [])
    status_by_rule: dict[str, ValidationStatus] = {}
    has_fail = False
    has_warning = False
    for result in results:
        status_by_rule[result.rule_id] = result.status
        if result.status == ValidationStatus.FAIL:
            has_fail = True
        elif result.status == ValidationStatus.WARNING:
            has_warning = True
    if has_fail:
        return QualityStatus.BLOCKED, [REASON_BLOCKED_CRITICAL_FAILURE]
    mandatory = _OPTIONAL_MANDATORY_RULES.get(record.category, ())
    if not mandatory:
        return QualityStatus.BLOCKED, [REASON_BLOCKED_CRITICAL_FAILURE]
    for rule_id in mandatory:
        if status_by_rule.get(rule_id) != ValidationStatus.PASS:
            # Missing / NOT_APPLICABLE / WARNING on a mandatory check => not
            # proven usable. Fail closed (never Medium from an empty set).
            return QualityStatus.BLOCKED, [REASON_BLOCKED_CRITICAL_FAILURE]
    if has_warning:
        return QualityStatus.LOW, [REASON_LOW_MATERIAL_FAILURE]
    return QualityStatus.MEDIUM, [REASON_MEDIUM_SINGLE_SOURCE]


def attach_record_quality(
    record: EvidenceRecord,
    results,
    policy: MarketPolicy | None = None,
) -> EvidenceRecord:
    """Return a new ``EvidenceRecord`` with its quality results attached.

    A frozen dataclass is rebuilt with the evaluated ``quality_status`` /
    ``quality_reasons`` and the fresh ``validation_results`` so downstream
    consumers see a self-consistent record without mutating the input.

    Optional-category records (fundamentals/news/sentiment) are classified by
    :func:`evaluate_optional_record_quality` from their own validator results, so
    a valid qualitative record (no numeric value) is ``Medium`` rather than
    forced to ``Low`` by the market OHLCV rule.
    """
    if record.category in _OPTIONAL_CATEGORIES:
        status, reasons = evaluate_optional_record_quality(record, results)
    else:
        status, reasons = evaluate_record_quality(record, results, policy)
    return EvidenceRecord.build(
        evidence_id=record.evidence_id,
        run_id=record.run_id,
        ticker_input=record.ticker_input,
        ticker_normalized=record.ticker_normalized,
        asset_type=record.asset_type,
        category=record.category,
        metric_name=record.metric_name,
        value_raw=record.value_raw,
        value_normalized=record.value_normalized,
        unit_raw=record.unit_raw,
        unit_normalized=record.unit_normalized,
        source_name=record.source_name,
        source_ref=record.source_ref,
        observed_at=record.observed_at,
        fetched_at=record.fetched_at,
        target_date=record.target_date,
        criticality=record.criticality,
        validation_results=list(results or []),
        quality_status=status,
        quality_reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Category aggregation
# ---------------------------------------------------------------------------


def _credible_sources(records: list[EvidenceRecord]) -> set[str]:
    """Unique source names among records that carry a real numeric value."""
    return {
        record.source_name
        for record in records
        if not is_sentinel(record) and record.value_normalized is not None
    }


def _critical_metrics(records: list[EvidenceRecord]) -> set[str]:
    return {r.metric_name for r in records if r.criticality == Criticality.CRITICAL}


def _cross_results_for_metric(
    metric: str,
    records: list[EvidenceRecord],
    results_by_id: dict[str, list],
) -> list:
    return [
        result
        for record in records
        if record.metric_name == metric
        for result in results_by_id.get(record.evidence_id, [])
        if result.validation_class == ValidationClass.CROSS_SOURCE_CONSISTENCY
    ]


def _critical_metrics_satisfied(
    records: list[EvidenceRecord],
    results_by_id: dict[str, list],
    policy: MarketPolicy,
) -> bool:
    """True iff every critical metric has >= min_independent_sources credible,
    mutually consistent (explicit PASS, no conflict) sources."""
    critical_metrics = _critical_metrics(records)
    if not critical_metrics:
        # No critical evidence: cannot claim High coverage.
        return False
    for metric in critical_metrics:
        metric_records = [r for r in records if r.metric_name == metric]
        if len(_credible_sources(metric_records)) < policy.min_independent_sources:
            return False
        cross = _cross_results_for_metric(metric, records, results_by_id)
        if any(r.status in (ValidationStatus.WARNING, ValidationStatus.FAIL) for r in cross):
            return False
        if not any(r.status == ValidationStatus.PASS for r in cross):
            return False
    return True


def aggregate_category_quality(
    category: str,
    records: list[EvidenceRecord],
    results_by_id: dict[str, list],
    policy: MarketPolicy | None = None,
) -> tuple[EvidenceGroupQuality, dict[str, QualityStatus]]:
    """Aggregate one category/group of market evidence into a group quality.

    Args:
        category: The category/group name (e.g. ``market``).
        records: The evidence records in this group.
        results_by_id: All ``ValidationResult`` objects keyed by ``evidence_id``.
        policy: Deterministic policy (source thresholds).

    Returns:
        A ``(EvidenceGroupQuality, per_record_statuses)`` tuple. The group
        quality follows the precedence in the module docstring.
    """
    policy = policy or MarketPolicy()
    per_status: dict[str, QualityStatus] = {}
    per_reasons: dict[str, list[str]] = {}
    for record in records:
        results = results_by_id.get(record.evidence_id, [])
        status, reasons = evaluate_record_quality(record, results, policy)
        per_status[record.evidence_id] = status
        per_reasons[record.evidence_id] = reasons

    criticality = _highest_criticality(records)
    evidence_ids = [record.evidence_id for record in records]
    credible = _credible_sources(records)
    credible_count = len(credible)

    blocked_ids = sorted(
        evidence_id
        for evidence_id, status in per_status.items()
        if status == QualityStatus.BLOCKED
    )
    if blocked_ids:
        reason = per_reasons[blocked_ids[0]]
        return (
            EvidenceGroupQuality(
                category=category,
                quality_status=QualityStatus.BLOCKED,
                criticality=criticality,
                evidence_ids=evidence_ids,
                source_count=credible_count,
                independent_source_count=credible_count,
                reason_codes=reason,
                human_readable_reason=(
                    "Blocked: " + "; ".join(dict.fromkeys(reason)) + " ("
                    + ",".join(blocked_ids) + ")."
                ),
            ),
            per_status,
        )

    low_ids = sorted(
        evidence_id
        for evidence_id, status in per_status.items()
        if status == QualityStatus.LOW
    )
    if low_ids:
        reason = per_reasons[low_ids[0]]
        return (
            EvidenceGroupQuality(
                category=category,
                quality_status=QualityStatus.LOW,
                criticality=criticality,
                evidence_ids=evidence_ids,
                source_count=credible_count,
                independent_source_count=credible_count,
                reason_codes=reason,
                human_readable_reason=(
                    "Low: material noncritical failure ("
                    + ", ".join(dict.fromkeys(reason)) + ")."
                ),
            ),
            per_status,
        )

    if credible_count == 0:
        return (
            EvidenceGroupQuality(
                category=category,
                quality_status=QualityStatus.LOW,
                criticality=criticality,
                evidence_ids=evidence_ids,
                source_count=0,
                independent_source_count=0,
                reason_codes=[REASON_LOW_NO_SOURCE],
                human_readable_reason="Low: no usable configured source.",
            ),
            per_status,
        )

    # All hard checks passed and at least one credible source exists. Determine
    # High vs Medium on whether EVERY critical metric is fully corroborated.
    if _critical_metrics_satisfied(records, results_by_id, policy):
        return (
            EvidenceGroupQuality(
                category=category,
                quality_status=QualityStatus.HIGH,
                criticality=criticality,
                evidence_ids=evidence_ids,
                source_count=credible_count,
                independent_source_count=credible_count,
                reason_codes=[REASON_HIGH],
                human_readable_reason=(
                    f"High: {credible_count} independent consistent sources on "
                    f"all critical metrics."
                ),
            ),
            per_status,
        )

    return (
        EvidenceGroupQuality(
            category=category,
            quality_status=QualityStatus.MEDIUM,
            criticality=criticality,
            evidence_ids=evidence_ids,
            source_count=credible_count,
            independent_source_count=credible_count,
            reason_codes=[REASON_MEDIUM_SINGLE_SOURCE],
            human_readable_reason=(
                "Medium: hard checks pass but not every critical metric is "
                "fully corroborated."
            ),
        ),
        per_status,
    )


# ---------------------------------------------------------------------------
# Optional-category aggregation (fundamentals / news / sentiment)
# ---------------------------------------------------------------------------

# Optional categories are qualitative/supporting: their records are never
# critical to the overall decision, and this aggregator deliberately does NOT
# reuse the market "High" rule (which demands corroborated *critical* metrics).
# News/post counts are not independent corroboration of a financial claim, so an
# optional category is never graded above Medium here.

REASON_OPTIONAL_MEDIUM: Final[str] = "optional_medium_records"
REASON_OPTIONAL_LOW_SINGLE: Final[str] = "optional_low_single_source"


def _optional_lineage_identity(record: EvidenceRecord) -> str:
    """Content lineage identity of an optional record (for independence).

    Independence must count distinct *content lineages*, not distinct provider
    wrapper names: two syndicated copies of one article, or two rows that came
    from the same filing/post, are NOT independent corroboration. The evidence_id
    embeds the lineage slug (``provider/wrapper`` is only its prefix), so this
    groups by the trailing lineage component; two records with identical
    content identity collapse to one independent lineage regardless of the
    provider label. Falls back to the source name when the id has no slug.
    """
    evidence_id = record.evidence_id or ""
    parts = evidence_id.rsplit("/", 2)
    if len(parts) == 3 and parts[1]:
        return parts[1]  # the deterministic lineage slug
    return record.source_name or evidence_id


def _optional_independent_sources(
    records: list[EvidenceRecord],
    per_status: dict[str, QualityStatus],
) -> set[str]:
    """Distinct independent content lineages among VALID (Medium) records.

    Only records the per-record evaluation accepted as ``Medium`` (validated,
    eligible) contribute; ``Low``/``Blocked``/excluded rows never inflate the
    count, and identical content lineage collapses to one independent source.
    """
    sources: set[str] = set()
    for record in records:
        if per_status.get(record.evidence_id) != QualityStatus.MEDIUM:
            continue
        if is_sentinel(record) or not (record.value_raw or "").strip():
            continue
        sources.add(_optional_lineage_identity(record))
    return sources


def aggregate_optional_category_quality(
    category: str,
    records: list[EvidenceRecord],
    results_by_id: dict[str, list],
    policy: Any | None = None,
) -> tuple[EvidenceGroupQuality, dict[str, QualityStatus]]:
    """Aggregate one OPTIONAL category's validated records into a group quality.

    Precedence:

    - any record evaluated ``Blocked`` -> group ``Blocked`` (the gate will still
      never let an optional block the run; this is a defensive mirror);
    - every record ``Low`` (or no usable record) -> group ``Low``;
    - at least one ``Medium`` record with >= ``min_independent_sources`` distinct
      **independent content lineages** -> group ``Medium`` (never ``High``: a
      qualitative category is not independent corroboration of a financial
      claim);
    - otherwise -> group ``Low``.

    ``policy`` is a :class:`~tradingagents.evidence.policy.CategoryPolicy` (which
    supplies ``min_independent_sources``) or a bundle exposing it; per-record
    classification uses the deterministic default record policy. Independent
    sources count valid eligible lineages only (never provider wrapper names or
    invalid rows). Records already excluded by the validator (future/malformed/
    undated) should not be passed here; the caller drops them.
    """
    min_independent = getattr(policy, "min_independent_sources", 1)
    try:
        min_independent = int(min_independent)
    except (TypeError, ValueError):
        min_independent = 1
    per_status: dict[str, QualityStatus] = {}
    per_reasons: dict[str, list[str]] = {}
    for record in records:
        results = results_by_id.get(record.evidence_id, [])
        # Optional qualitative records must not be forced through the OHLCV
        # numeric rule (a text value is not "unusable"): classify from their own
        # per-category validator results instead.
        status, reasons = evaluate_optional_record_quality(record, results)
        per_status[record.evidence_id] = status
        per_reasons[record.evidence_id] = reasons

    evidence_ids = sorted(r.evidence_id for r in records)
    sources = _optional_independent_sources(records, per_status)
    source_count = len(sources)
    criticality = Criticality.IMPORTANT

    blocked = [eid for eid, st in per_status.items() if st == QualityStatus.BLOCKED]
    if blocked:
        reasons = per_reasons[blocked[0]]
        return (
            EvidenceGroupQuality(
                category=category,
                quality_status=QualityStatus.BLOCKED,
                criticality=criticality,
                evidence_ids=evidence_ids,
                source_count=source_count,
                independent_source_count=source_count,
                reason_codes=list(dict.fromkeys(reasons)),
                human_readable_reason=(
                    "Blocked: optional record failed hard validation; not decisive."
                ),
            ),
            per_status,
        )

    has_medium = any(st == QualityStatus.MEDIUM for st in per_status.values())
    if has_medium and source_count >= min_independent:
        return (
            EvidenceGroupQuality(
                category=category,
                quality_status=QualityStatus.MEDIUM,
                criticality=criticality,
                evidence_ids=evidence_ids,
                source_count=source_count,
                independent_source_count=source_count,
                reason_codes=[REASON_OPTIONAL_MEDIUM],
                human_readable_reason=(
                    f"Medium: {source_count} validated structured source(s); "
                    "qualitative category, never counted as corroboration."
                ),
            ),
            per_status,
        )

    if source_count <= 1:
        reason_codes = [REASON_OPTIONAL_LOW_SINGLE]
    else:
        reason_codes = [REASON_LOW_MATERIAL_FAILURE]
    return (
        EvidenceGroupQuality(
            category=category,
            quality_status=QualityStatus.LOW,
            criticality=criticality,
            evidence_ids=evidence_ids,
            source_count=source_count,
            independent_source_count=source_count,
            reason_codes=reason_codes,
            human_readable_reason=(
                "Low: optional evidence is single-source or not fully validated; "
                "it degrades but cannot be decisive."
            ),
        ),
        per_status,
    )
