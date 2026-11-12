"""Evidence foundation for the deterministic Data Quality Gate.

This package holds the typed, deterministic, JSON-safe records the quality
gate operates on (``models``), plus the deterministic Step 2 core:

- ``adapter`` — truthful ``StructuredSnapshot`` to ``EvidenceRecord`` adapter.
- ``validate`` — the five deterministic validation classes for market records.
- ``policy`` — deterministic Decimal-threshold policy objects.
- ``quality`` — per-record precedence and per-category aggregation.
- ``gate`` — ``GateDecision`` generation with injectable ``decided_at``.

The records are:

- ``EvidenceRecord`` — one row of quantitative/text evidence with a normalized
  value and provenance, exactly the locked 20 fields.
- ``SourceAttempt`` — a separate, never-embedded record describing one attempt
  to fetch data from a source/tool (exactly 7 fields).
- ``ValidationResult`` — the outcome of validating one evidence record against
  one of the five deterministic validation classes.
- ``EvidenceGroupQuality`` — the aggregated quality state of a group of
  evidence records.
- ``GateDecision`` — the gate's verdict and the routing it implies.

Nothing here nests a ``SourceAttempt`` inside an ``EvidenceRecord``, and
``ValidationResult`` never holds a reference back to its owning
``EvidenceRecord`` (it carries only the ``evidence_id`` string), so
serialization is acyclic.

Numeric normalization uses :class:`decimal.Decimal` (or explicitly quantized
values) for financial comparisons; ``to_dict``/``from_dict`` serialize them
deterministically and JSON-safely.
"""

from __future__ import annotations

from tradingagents.evidence.adapter import (
    build_market_evidence_records,
    make_market_evidence_id,
)
from tradingagents.evidence.gate import (
    build_gate_decision,
    build_multi_category_gate_decision,
    build_unavailable_category,
)
from tradingagents.evidence.models import (
    Criticality,
    EvidenceGroupQuality,
    EvidenceRecord,
    GateDecision,
    GateVerdict,
    QualityStatus,
    SourceAttempt,
    SourceResultStatus,
    ValidationClass,
    ValidationResult,
    ValidationStatus,
    quantize_decimal,
)
from tradingagents.evidence.policy import (
    CATEGORY_FUNDAMENTALS,
    CATEGORY_MARKET,
    CATEGORY_NEWS,
    CATEGORY_SENTIMENT,
    DEFAULT_MARKET_POLICY,
    DEFAULT_MULTI_CATEGORY_POLICY,
    OPTIONAL_CATEGORIES,
    CategoryPolicy,
    CategoryRole,
    MarketPolicy,
    MarketRecordPolicy,
    MetricTolerance,
    MultiCategoryPolicy,
    count_business_days,
)
from tradingagents.evidence.quality import (
    aggregate_category_quality,
    attach_record_quality,
    evaluate_record_quality,
)
from tradingagents.evidence.validate import (
    cross_source_consistency_results,
    ohlc_relationship_results,
    validate_market_records,
)

__all__ = [
    "EvidenceRecord",
    "SourceAttempt",
    "ValidationResult",
    "EvidenceGroupQuality",
    "GateDecision",
    "Criticality",
    "QualityStatus",
    "GateVerdict",
    "ValidationStatus",
    "SourceResultStatus",
    "ValidationClass",
    "quantize_decimal",
    # Step 2: adapter
    "build_market_evidence_records",
    "make_market_evidence_id",
    # Step 2: validator
    "validate_market_records",
    "ohlc_relationship_results",
    "cross_source_consistency_results",
    # Step 2: policy
    "MarketPolicy",
    "MarketRecordPolicy",
    "MetricTolerance",
    "DEFAULT_MARKET_POLICY",
    "count_business_days",
    # Step 2: quality
    "evaluate_record_quality",
    "attach_record_quality",
    "aggregate_category_quality",
    # Step 2: gate
    "build_gate_decision",
    # Stage 2: multi-category gate
    "build_multi_category_gate_decision",
    "build_unavailable_category",
    "CategoryRole",
    "CategoryPolicy",
    "MultiCategoryPolicy",
    "DEFAULT_MULTI_CATEGORY_POLICY",
    "OPTIONAL_CATEGORIES",
    "CATEGORY_MARKET",
    "CATEGORY_FUNDAMENTALS",
    "CATEGORY_NEWS",
    "CATEGORY_SENTIMENT",
]
