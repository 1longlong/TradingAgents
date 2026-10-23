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
from tradingagents.evidence.models import Criticality, EvidenceGroupQuality, GateDecision
from tradingagents.evidence.policy import (
    OPTIONAL_CATEGORIES,
    MultiCategoryPolicy,
)
from tradingagents.evidence.quality import aggregate_category_quality
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
    ) -> None:
        self.verdict = verdict
        self.groups = groups
        self.gate_decision = gate_decision
        self.evidence_records = evidence_records
        self.validation_results = validation_results
        self.context = context
        self.error = error

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

    # ---- Optional categories ----
    # Each optional category uses the explicit structured contract group when one
    # is supplied; otherwise it is absent and yields a deterministic explicit
    # unavailable/insufficient result with stable reasons. Optional categories
    # are never parsed from analyst prose and never block a run.
    groups: list[EvidenceGroupQuality] = [market_group]
    supplied = optional_category_groups or {}
    for category in OPTIONAL_CATEGORIES:
        category_policy = resolved_policy.optional.get(category)
        group = _resolve_optional_group(
            category, supplied, category_policy
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
        evidence_records=[r.to_dict() for r in records],
        validation_results={
            str(eid): [r.to_dict() for r in rs]
            for eid, rs in results_by_id.items()
        },
        context=_build_multi_context(decision),
        error=None,
    )


def _resolve_optional_group(
    category: str,
    supplied: Mapping[str, EvidenceGroupQuality],
    category_policy: Any,
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
    group = supplied.get(category)
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
