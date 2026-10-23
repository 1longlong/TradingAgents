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

from typing import Final

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


def attach_record_quality(
    record: EvidenceRecord,
    results,
    policy: MarketPolicy | None = None,
) -> EvidenceRecord:
    """Return a new ``EvidenceRecord`` with its quality results attached.

    A frozen dataclass is rebuilt with the evaluated ``quality_status`` /
    ``quality_reasons`` and the fresh ``validation_results`` so downstream
    consumers see a self-consistent record without mutating the input.
    """
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
