"""Stage 2 multi-category gate engine: evaluates market + optional categories.

This pure, dependency-injectable engine turns the *available structured inputs*
into per-category :class:`EvidenceGroupQuality` objects and a single
:class:`GateDecision` via :func:`build_multi_category_gate_decision`.

Design rules (authoritative):

- **Truthful, no prose parsing.** Only structured inputs are consumed. For the
  ``market`` category the structured verified snapshot is adapted to
  :class:`EvidenceRecord` records and validated (as in Stage 1). For the
  optional categories (``fundamentals``, ``news``, ``sentiment``) this codebase
  exposes **no** structured source — only prose reports — so those categories
  produce an explicit deterministic *unavailable* result with stable reasons,
  never fabricated source/date/unit/confidence and never analyst-prose parsing.
  Trustworthy structured optional-category evidence enters **only** through the
  explicit ``optional_category_groups`` contract (already-validated
  ``EvidenceGroupQuality``); anything absent yields unavailable/insufficient.
- **Market is fail-closed.** A missing/blocked market category always yields a
  ``blocked`` verdict.
- **Optional categories degrade under a versioned policy.** An unavailable
  optional category lowers the verdict to ``degraded`` only when the policy so
  requires; it never blocks the run.
- **Deterministic.** The engine accepts injectable builders/validators/aggregator
  and a fixed ``now_provider`` so tests can pin behavior without a network or a
  live clock. The ``run_id`` is derived from ``(trade_date, normalized symbol)``.
- **JSON-safe output.** The engine returns plain dicts/lists/strings for the
  state and for the report artifacts (the serialized ``to_dict()`` forms).

The engine is pure and lives in the evidence layer; it does **not** import the
graph package, so the LangGraph node can delegate to it without a circular
import. The same pure evaluation is reused by the report-artifact writer and by
tests without re-entering LangGraph.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tradingagents.dataflows.market_data_validator import (
    StructuredSnapshot,
    build_verified_market_snapshot_data,
)
from tradingagents.evidence.adapter import MARKET_CATEGORY, build_market_evidence_records
from tradingagents.evidence.gate import (
    build_multi_category_gate_decision,
    build_unavailable_category,
)
from tradingagents.evidence.models import (
    Criticality,
    EvidenceGroupQuality,
    GateDecision,
    QualityStatus,
)
from tradingagents.evidence.policy import (
    OPTIONAL_CATEGORIES,
    MultiCategoryPolicy,
)
from tradingagents.evidence.quality import (
    aggregate_category_quality,
    aggregate_optional_category_quality,
    attach_record_quality,
)
from tradingagents.evidence.validate import validate_market_records

_DEFAULT_ASSET_TYPE = "stock"


def _default_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_symbol(symbol: str) -> str:
    from tradingagents.dataflows.symbol_utils import normalize_symbol

    return normalize_symbol(symbol)


def build_multi_category_run_id(trade_date: str, symbol_normalized: str) -> str:
    """Stable deterministic run id derived from ``(trade_date, symbol)``.

    Mirrors the market gate's run id so evidence IDs and the gate output are
    reproducible for the same ``(symbol, requested_date)`` and never depend on
    wall-clock time.
    """
    return f"{str(trade_date)}/{symbol_normalized}"


class MultiCategoryGateResult:
    """Deterministic result bundle of a multi-category gate evaluation.

    Plain JSON-safe ``to_dict``-able surface: holds the serialized evidence
    records, validation results, per-category group statuses, the gate decision,
    and the human-readable context. Kept as a small typed holder so tests and
    the report writer can consume the same structure without re-deriving it.
    """

    def __init__(
        self,
        *,
        verdict: str,
        groups: list[dict[str, Any]],
        gate_decision: GateDecision,
        evidence_records: list[dict[str, Any]],
        validation_results: dict[str, Any],
        context: str,
        error: str | None,
        pruned_record_ids: list[str] | None = None,
    ) -> None:
        self.verdict = verdict
        self.groups = groups
        self.gate_decision = gate_decision
        self.evidence_records = evidence_records
        self.validation_results = validation_results
        self.context = context
        self.error = error
        # Records that were captured but excluded (future/malformed/undated) at
        # this gate run; they are NOT decisive and are pruned from persisted
        # ingest state so a later resume cannot resurrect them as evidence.
        self.pruned_record_ids = list(pruned_record_ids or [])

    def to_dict(self) -> dict[str, Any]:
        """The report-facing JSON-safe dict for this gate result."""
        return {
            "verdict": self.verdict,
            "groups": list(self.groups),
            "gate_decision": self.gate_decision.to_dict(),
            "evidence_records": list(self.evidence_records),
            "validation_results": dict(self.validation_results),
            "context": self.context,
            "error": self.error,
        }


def evaluate_multi_category_gate(
    *,
    trade_date: str,
    symbol: str,
    asset_type: str = _DEFAULT_ASSET_TYPE,
    look_back_days: int = 30,
    snapshot_builder: Callable[..., StructuredSnapshot] = build_verified_market_snapshot_data,
    record_builder: Callable = build_market_evidence_records,
    validator: Callable = validate_market_records,
    aggregator: Callable = aggregate_category_quality,
    policy: MultiCategoryPolicy | None = None,
    now_provider: Callable[[], str] = _default_now_iso,
    market_policy: Any = None,
    run_id_builder: Callable[[str, str], str] = build_multi_category_run_id,
    optional_category_groups: Mapping[str, EvidenceGroupQuality] | None = None,
    captured_optional_records: Mapping[str, list[Any]] | None = None,
    optional_validator: Callable | None = None,
    optional_record_aggregator: Callable | None = None,
) -> MultiCategoryGateResult:
    """Evaluate the market category plus the optional categories.

    Args:
        trade_date: The requested analysis date (``YYYY-MM-DD``).
        symbol: The company/ticker under analysis.
        asset_type: Expected asset type (default ``stock``).
        look_back_days: History window for the market snapshot builder.
        snapshot_builder: Builds the verified market snapshot (injectable).
        record_builder: Adapts a snapshot to ``EvidenceRecord`` objects.
        validator: Validates market records against the five classes.
        aggregator: Aggregates per-category quality.
        policy: The :class:`MultiCategoryPolicy` bundle.
        now_provider: Deterministic ``decided_at`` provider.
        market_policy: The :class:`MarketPolicy` for market validation (falls back
            to ``None``, letting the validator use its default).
        run_id_builder: Deterministic run-id builder from ``(trade_date, symbol)``.
        optional_category_groups: **Explicit structured contract** mapping an
            optional category name to its already-validated
            :class:`EvidenceGroupQuality`. This is the only way trustworthy
            structured optional-category evidence gets in — never parsed from
            analyst prose. A category absent here (or in the policy) yields an
            explicit deterministic ``unavailable``/``insufficient`` result
            instead of a fabricated one.
        captured_optional_records: Typed optional-category records actually
            captured from a configured vendor source in this run, keyed by
            category (ADR-008 automatic path). Each record is validated per
            category and aggregated for real; excluded (future/malformed/
            undated) records are dropped from the serialized set and never
            count. Per-record validations are merged into the result so the
            manifest/allowlist/report see them.
        optional_validator: Per-category validator for captured records
            (defaults to ``validate_optional_records``).
        optional_record_aggregator: Aggregator for captured optional records
            (defaults to ``aggregate_optional_category_quality``).

    Returns:
        A :class:`MultiCategoryGateResult` with the market group (validated) and
        one group per optional category (the structured contract result when
        supplied, else an explicit unavailable result). The verdict follows the
        authoritative precedence (market critical fail-closed; optional
        categories degrade under the policy, never block).
    """
    resolved_policy = policy or _default_multi_category_policy()

    normalized = _normalize_symbol(symbol)
    run_id = run_id_builder(trade_date, normalized)
    decided_at = now_provider()

    # ---- Market (critical, fail closed) ----
    snapshot = snapshot_builder(symbol, trade_date, look_back_days=look_back_days)
    records = record_builder(snapshot, run_id, ticker_input=symbol)
    results_by_id = validator(
        records,
        expected_symbol=normalized,
        target_date=trade_date,
        expected_asset_type=asset_type,
        policy=market_policy,
    )
    market_group, _per_record = aggregator(
        MARKET_CATEGORY, records, results_by_id, policy=market_policy
    )

    # Apply EACH record's own computed classification, quality reasons, and
    # validation results before serializing. The aggregator returns the group
    # rating and a per-record status map; the provisional adapter records still
    # carry ``Low``/``unvalidated`` until this step, so without it downstream
    # consumers (manifest, citation allowlist, debate, report) see no qualified
    # evidence for a run the gate judged normal/degraded (review finding 2).
    # This is a per-record assignment, never a promotion of every record from the
    # group rating: an individually Low/Blocked record stays Low/Blocked.
    classified_records = [
        attach_record_quality(record, results_by_id.get(record.evidence_id, []), market_policy)
        for record in records
    ]

    # ---- Captured optional categories (ADR-008 automatic path) ----
    # Typed vendor-origin records are validated per category and aggregated for
    # real; the market serialized set is extended so one manifest carries both
    # critical and optional evidence. Excluded records (future/malformed/undated)
    # never count.
    serialized_records = list(classified_records)
    merged_validations = {
        str(eid): [r.to_dict() for r in rs] for eid, rs in results_by_id.items()
    }
    pruned: list[str] = []
    captured_groups = _evaluate_captured_optional(
        captured_optional_records or {},
        trade_date=trade_date,
        normalized=normalized,
        validators=optional_validator,
        aggregator=optional_record_aggregator,
        policy=resolved_policy,
        serialized_records=serialized_records,
        merged_validations=merged_validations,
        market_policy=market_policy,
        pruned_record_ids=pruned,
    )

    # ---- Optional categories ----
    # Captured real records win; otherwise the explicit structured contract
    # group (compatible, but never able to raise quality above what records
    # support); otherwise an explicit unavailable result. Optional categories are
    # never parsed from analyst prose and never block a run.
    groups: list[EvidenceGroupQuality] = [market_group]
    supplied = optional_category_groups or {}
    for category in OPTIONAL_CATEGORIES:
        category_policy = resolved_policy.optional.get(category)
        group = _resolve_optional_group(
            category, supplied, category_policy, captured_groups.get(category)
        )
        groups.append(group)

    decision = build_multi_category_gate_decision(
        groups,
        decided_at=decided_at,
        policy=resolved_policy,
    )

    return MultiCategoryGateResult(
        verdict=decision.decision.value,
        groups=[g.to_dict() for g in decision.group_statuses],
        gate_decision=decision,
        evidence_records=[r.to_dict() for r in serialized_records],
        validation_results=merged_validations,
        context=_build_multi_context(decision),
        error=None,
        pruned_record_ids=pruned,
    )


def _evaluate_captured_optional(
    captured: Mapping[str, list[Any]],
    *,
    trade_date: str,
    normalized: str,
    validators: Callable | None,
    aggregator: Callable | None,
    policy: MultiCategoryPolicy,
    serialized_records: list,
    merged_validations: dict,
    market_policy: Any,
    pruned_record_ids: list,
) -> dict[str, EvidenceGroupQuality]:
    """Validate + aggregate captured optional records into category groups.

    Mutates ``serialized_records`` (appending non-excluded classified optional
    records), ``merged_validations`` (recording every record's validations,
    including excluded ones so the audit shows WHY they were dropped), and
    ``pruned_record_ids`` (appending the IDs of excluded records so the gate can
    prune them from persisted ingest state). Returns the per-category group
    quality for categories that had captured records.
    """
    if not captured:
        return {}
    if validators is None:
        from tradingagents.evidence.vendor_adapters import validate_optional_records

        validators = validate_optional_records
    if aggregator is None:
        aggregator = aggregate_optional_category_quality

    groups: dict[str, EvidenceGroupQuality] = {}
    for category in OPTIONAL_CATEGORIES:
        records = [r for r in captured.get(category, []) if r.category == category]
        if not records:
            continue
        results_by_id = validators(
            {category: records},
            expected_symbol=normalized,
            target_date=trade_date,
        )
        # Resolve the category's OWN CategoryPolicy for the group aggregation:
        # ``aggregate_optional_category_quality`` reads ``min_independent_sources``
        # from a CategoryPolicy, NOT the MultiCategoryPolicy bundle. Passing the
        # bundle would silently fall back to a numeric default. Per-record
        # classification (below) keeps the separate MarketPolicy.
        category_policy = policy.optional.get(category)
        aggregate_policy = category_policy if category_policy is not None else policy
        group, _per_status = aggregator(category, records, results_by_id, policy=aggregate_policy)
        groups[category] = group
        for record in records:
            record_results = results_by_id.get(record.evidence_id, [])
            merged_validations[record.evidence_id] = [
                r.to_dict() for r in record_results
            ]
            if _is_excluded(record_results):
                pruned_record_ids.append(record.evidence_id)
                continue
            serialized_records.append(
                attach_record_quality(record, record_results, market_policy)
            )
    return groups


def _is_excluded(results: list) -> bool:
    """True iff a record failed a freshness/look-ahead/completeness check."""
    from tradingagents.evidence.models import ValidationClass, ValidationStatus

    for result in results:
        if result.status == ValidationStatus.FAIL and result.validation_class in (
            ValidationClass.FRESHNESS_LOOKAHEAD,
            ValidationClass.COMPLETENESS,
        ):
            return True
    return False


def _resolve_optional_group(
    category: str,
    supplied: Mapping[str, EvidenceGroupQuality],
    category_policy: Any,
    captured_group: EvidenceGroupQuality | None = None,
) -> EvidenceGroupQuality:
    """Resolve one optional category's group quality from the explicit contract.

    - A category in ``supplied`` uses its structured ``EvidenceGroupQuality``,
      clamped to ``IMPORTANT`` criticality so an optional category can **never**
      escalate to a critical fail-closed role (it only degrades under policy).
    - A category absent from ``supplied`` (the honest state for an optional
      category with no trustworthy structured source) yields an explicit
      deterministic unavailable/insufficient result with stable reasons and zero
      (never fabricated) sources.

    Never parses analyst prose and never invents a source/date/unit/confidence.
    """
    # A captured, record-backed group is authoritative: real validated records
    # beat a manually claimed grade. A manual group can only appear when no
    # records were captured, and even then its quality never exceeds what the
    # record-less state supports (it stays LOW, see below).
    if captured_group is not None:
        group = captured_group
    else:
        group = supplied.get(category)
        # Manual contract stays compatible but is weakest: without records behind
        # it, a claimed High/Medium grade is clamped to at most LOW so it can
        # never fabricate a high optional grade.
        if group is not None and group.quality_status in (
            QualityStatus.HIGH,
            QualityStatus.MEDIUM,
        ):
            return EvidenceGroupQuality(
                category=group.category,
                quality_status=QualityStatus.LOW,
                criticality=(
                    Criticality.IMPORTANT
                    if group.criticality == Criticality.CRITICAL
                    else group.criticality
                ),
                evidence_ids=[],
                source_count=0,
                independent_source_count=0,
                reason_codes=["manual_group_without_records"],
                human_readable_reason=(
                    "Low: a manually supplied optional grade without captured "
                    "structured records is not trusted as High/Medium."
                ),
            )
    if group is not None:
        if not isinstance(group, EvidenceGroupQuality):
            raise ValueError(
                f"optional_category_groups[{category!r}] must be "
                f"EvidenceGroupQuality, got {type(group).__name__}"
            )
        # Optional categories degrade but never block: clamp any defensive
        # CRITICAL marking down to IMPORTANT.
        criticality = (
            Criticality.IMPORTANT
            if group.criticality == Criticality.CRITICAL
            else group.criticality
        )
        return EvidenceGroupQuality(
            category=group.category,
            quality_status=group.quality_status,
            criticality=criticality,
            evidence_ids=list(group.evidence_ids),
            source_count=group.source_count,
            independent_source_count=group.independent_source_count,
            reason_codes=list(group.reason_codes),
            human_readable_reason=group.human_readable_reason,
        )
    return build_unavailable_category(
        category,
        policy_version=(
            category_policy.policy_version if category_policy else "1.0"
        ),
    )


def _default_multi_category_policy() -> MultiCategoryPolicy:
    """Module-local default to avoid a circular import at module load."""
    from tradingagents.evidence.policy import DEFAULT_MULTI_CATEGORY_POLICY

    return DEFAULT_MULTI_CATEGORY_POLICY


def _build_multi_context(decision: GateDecision) -> str:
    """Human-readable multi-category gate context for downstream prompts.

    States the verdict, the market ground-truth requirement, and — for
    optional categories that are unavailable — the explicit limitation so the
    debate never treats missing fundamentals/news/sentiment quality as a pass.
    """
    verdict = decision.decision.value
    lines: list[str] = ["[Data Quality Gate]", f"Verdict: {verdict}."]

    if verdict == "blocked":
        lines.append(
            "Critical market data is missing or conflicting; the standard "
            "bull/bear debate was skipped. Only an evidence-insufficient "
            "conclusion may be produced. No directional Buy or Sell is permitted."
        )
    elif verdict == "degraded":
        lines.append(
            "Market data is adequate but one or more optional evidence "
            "categories (fundamentals, news, sentiment) have no trustworthy "
            "structured source. Those categories are degraded, so confidence is "
            "capped and low-evidence claims cannot be decisive."
        )
    else:
        lines.append(
            "Market data is adequate with all evaluated categories available: "
            "the standard bull/bear debate may proceed with normal confidence."
        )

    if decision.human_readable_reason:
        lines.append("Reason: " + _sentence(decision.human_readable_reason))
    if decision.limitations:
        lines.append("Limitations: " + _sentence("; ".join(decision.limitations)))
    return "\n".join(lines)


def _sentence(text: str) -> str:
    """Return ``text`` with exactly one trailing period, never two."""
    return text.rstrip(".") + "."
