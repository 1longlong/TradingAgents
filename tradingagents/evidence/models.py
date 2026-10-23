"""Typed, deterministic, JSON-safe evidence schemas for the Data Quality Gate.

Design constraints (frozen for the implementation):

- ``EvidenceRecord`` has **exactly** the 20 locked fields and no extras. It is
  constructed from validated parts; ``to_dict``/``from_dict`` are the only
  serialization surfaces and are acyclic. ``value_raw`` and the unit fields are
  strings so the same shape carries both numeric and text evidence without
  adding fields.
- ``SourceAttempt`` is a **separate** record with exactly 7 fields and is never
  embedded in ``EvidenceRecord``.
- ``ValidationResult`` carries a back-reference by ``evidence_id`` string only;
  it never holds an ``EvidenceRecord``. This keeps serialization acyclic.
- Normalized financial values, thresholds, and tolerances are ``Decimal``
  (or explicitly quantized). ``quantize_decimal`` is the single quantization
  helper so the package is consistent.
- ``to_dict`` output is JSON-safe: ``Decimal`` becomes a fixed-precision string,
  ``datetime`` becomes ISO strings, enums become their stable ``value``.
  Order is fixed and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

# Fixed precision for every normalized financial value, so Decimals round-trip
# deterministically and never carry float noise. See ``quantize_decimal``.
DEFAULT_QUANTIZE = Decimal("0.0000000001")


def quantize_decimal(value: Any, scale: Decimal | None = None) -> Decimal | None:
    """Return ``value`` as a ``Decimal`` quantized to ``scale``.

    ``None`` stays ``None``. Neither a bool nor a NaN/inf is a financial
    magnitude, so those return ``None`` (represented structurally as an absent
    value rather than silently coerced). Floats go through ``str()`` to avoid
    binary float noise. Unparseable input returns ``None``.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        magnitude = value
    elif isinstance(value, int):
        magnitude = Decimal(value)
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):  # NaN/inf
            return None
        magnitude = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        try:
            magnitude = Decimal(text)
        except ArithmeticError:
            return None
        if not magnitude.is_finite():
            return None
    else:
        return None
    if not magnitude.is_finite():
        return None
    return magnitude.quantize(scale or DEFAULT_QUANTIZE, rounding=ROUND_HALF_UP)


def _json_safe(value: Any) -> Any:
    """Coerce a value to a JSON-serialisable primitive.

    ``Decimal`` → its fixed-precision string; ``datetime`` → ISO string; enums →
    ``value``; lists/dicts recurse; any other object is stringified so the
    payload is always ``json.dumps``-able.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        # Quantize first so every serialization surface emits the same
        # fixed-precision string (consistent with EvidenceRecord.to_dict).
        quantized = quantize_decimal(value)
        return str(quantized) if quantized is not None else None
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (int, float, str)):
        if isinstance(value, float) and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _format_datetime(value: datetime) -> str:
    """Deterministic ISO string for a ``datetime``.

    A tz-aware value is converted to UTC and rendered ``YYYY-MM-DDTHH:MM:SSZ``;
    a naive value is rendered ``YYYY-MM-DDTHH:MM:SS``.
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Criticality(str, Enum):
    """How central an evidence record is to the decision."""

    CRITICAL = "critical"
    IMPORTANT = "important"
    SUPPORTING = "supporting"


class QualityStatus(str, Enum):
    """Per-evidence and per-group quality state."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    BLOCKED = "Blocked"


class GateVerdict(str, Enum):
    """Three-way routing outcome of the gate."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class ValidationStatus(str, Enum):
    """Outcome of a single validation check."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class SourceResultStatus(str, Enum):
    """Outcome of a single source attempt (fetch) call."""

    SUCCESS = "success"
    EMPTY = "empty"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationClass(str, Enum):
    """The five deterministic validation classes."""

    COMPLETENESS = "completeness"
    FRESHNESS_LOOKAHEAD = "freshness_lookahead"
    FORMAT_NUMERIC = "format_numeric"
    ASSET_APPLICABILITY = "asset_applicability"
    CROSS_SOURCE_CONSISTENCY = "cross_source_consistency"


VALIDATION_CLASSES: tuple[str, ...] = tuple(c.value for c in ValidationClass)


# ---------------------------------------------------------------------------
# ValidationResult — the five validation classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating one evidence record against one check.

    Retains ``rule_id``, one of the five exact ``ValidationClass`` values,
    ``expected``/``actual`` (stored as JSON-safe primitives), ``message``, and
    the owning ``evidence_id`` string reference. It never holds an
    ``EvidenceRecord`` object, so serialization stays acyclic.
    """

    rule_id: str
    validation_class: ValidationClass
    status: ValidationStatus
    expected: Any = None
    actual: Any = None
    message: str = ""
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.validation_class, ValidationClass):
            object.__setattr__(
                self, "validation_class", ValidationClass(str(self.validation_class))
            )
        if not isinstance(self.status, ValidationStatus):
            object.__setattr__(self, "status", ValidationStatus(str(self.status)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "validation_class": self.validation_class.value,
            "status": self.status.value,
            "expected": _json_safe(self.expected),
            "actual": _json_safe(self.actual),
            "message": self.message,
            "evidence_id": self.evidence_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidationResult:
        return cls(
            rule_id=str(data.get("rule_id", "")),
            validation_class=ValidationClass(
                data.get("validation_class", ValidationClass.COMPLETENESS.value)
            ),
            status=ValidationStatus(
                data.get("status", ValidationStatus.NOT_APPLICABLE.value)
            ),
            expected=data.get("expected"),
            actual=data.get("actual"),
            message=str(data.get("message", "")),
            evidence_id=str(data.get("evidence_id", "")),
        )


# ---------------------------------------------------------------------------
# SourceAttempt — separate record, never embedded
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceAttempt:
    """One attempt to retrieve data from a source via a tool.

    Deliberately **not** embedded in ``EvidenceRecord``: a single evidence
    record may be corroborated by several attempts, or an attempt may yield no
    evidence at all, so the attempt is tracked as a sibling record keyed by
    ``source`` + ``started_at``. Exactly the 7 locked fields.
    """

    source: str
    tool: str
    started_at: str | None
    duration: float | None
    result_status: SourceResultStatus
    error_type: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.result_status, SourceResultStatus):
            object.__setattr__(
                self, "result_status", SourceResultStatus(str(self.result_status))
            )
        if self.duration is not None and self.duration < 0:
            raise ValueError(f"duration must be >= 0, got {self.duration}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "tool": self.tool,
            "started_at": self.started_at,
            "duration": self.duration,
            "result_status": self.result_status.value,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceAttempt:
        return cls(
            source=str(data.get("source", "")),
            tool=str(data.get("tool", "")),
            started_at=data.get("started_at"),
            duration=data.get("duration"),
            result_status=SourceResultStatus(
                data.get("result_status", SourceResultStatus.SKIPPED.value)
            ),
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
        )


# ---------------------------------------------------------------------------
# EvidenceRecord — exactly the locked 20 fields
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRecord:
    """One row of deterministic evidence.

    Exactly the 20 locked fields. ``value_raw`` and the unit fields are strings
    so the same shape carries numeric and text evidence without adding fields;
    ``value_normalized`` is the quantized ``Decimal`` for numeric evidence and
    ``None`` for text evidence (an absent value is represented structurally,
    never as a coerced number).

    ``validation_results`` holds the ``ValidationResult`` objects produced for
    this record; they are flattened to dicts on serialization and reference this
    record by ``evidence_id`` string only.
    """

    evidence_id: str
    run_id: str
    ticker_input: str
    ticker_normalized: str
    asset_type: str
    category: str
    metric_name: str
    value_raw: str
    value_normalized: Decimal | None
    unit_raw: str
    unit_normalized: str | None
    source_name: str
    source_ref: str
    observed_at: str | None
    fetched_at: str | None
    target_date: str | None
    criticality: Criticality
    validation_results: list[ValidationResult]
    quality_status: QualityStatus
    quality_reasons: list[str]

    def __post_init__(self) -> None:
        if not isinstance(self.criticality, Criticality):
            object.__setattr__(self, "criticality", Criticality(str(self.criticality)))
        if not isinstance(self.quality_status, QualityStatus):
            object.__setattr__(
                self, "quality_status", QualityStatus(str(self.quality_status))
            )
        value_normalized = quantize_decimal(self.value_normalized)
        if value_normalized is not None:
            object.__setattr__(self, "value_normalized", value_normalized)
        # ValidationResults are owned by this record; they never own it back.
        object.__setattr__(
            self,
            "validation_results",
            list(self.validation_results) if self.validation_results else [],
        )
        object.__setattr__(self, "quality_reasons", list(self.quality_reasons or []))

    @classmethod
    def build(
        cls,
        *,
        evidence_id: str,
        run_id: str,
        ticker_input: str,
        ticker_normalized: str,
        asset_type: str,
        category: str,
        metric_name: str,
        value_raw: str,
        value_normalized: Decimal | None,
        unit_raw: str,
        unit_normalized: str | None,
        source_name: str,
        source_ref: str,
        observed_at: str | None,
        fetched_at: str | None,
        target_date: str | None,
        criticality: Criticality,
        validation_results: list[ValidationResult],
        quality_status: QualityStatus = QualityStatus.HIGH,
        quality_reasons: list[str] | None = None,
) -> EvidenceRecord:
        return cls(
            evidence_id=evidence_id,
            run_id=run_id,
            ticker_input=ticker_input,
            ticker_normalized=ticker_normalized,
            asset_type=asset_type,
            category=category,
            metric_name=metric_name,
            value_raw=value_raw,
            value_normalized=value_normalized,
            unit_raw=unit_raw,
            unit_normalized=unit_normalized,
            source_name=source_name,
            source_ref=source_ref,
            observed_at=observed_at,
            fetched_at=fetched_at,
            target_date=target_date,
            criticality=criticality,
            validation_results=validation_results,
            quality_status=quality_status,
            quality_reasons=quality_reasons or [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "ticker_input": self.ticker_input,
            "ticker_normalized": self.ticker_normalized,
            "asset_type": self.asset_type,
            "category": self.category,
            "metric_name": self.metric_name,
            "value_raw": self.value_raw,
            "value_normalized": (
                str(self.value_normalized) if self.value_normalized is not None else None
            ),
            "unit_raw": self.unit_raw,
            "unit_normalized": self.unit_normalized,
            "source_name": self.source_name,
            "source_ref": self.source_ref,
            "observed_at": self.observed_at,
            "fetched_at": self.fetched_at,
            "target_date": self.target_date,
            "criticality": self.criticality.value,
            "validation_results": [v.to_dict() for v in self.validation_results],
            "quality_status": self.quality_status.value,
            "quality_reasons": list(self.quality_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRecord:
        return cls(
            evidence_id=str(data.get("evidence_id", "")),
            run_id=str(data.get("run_id", "")),
            ticker_input=str(data.get("ticker_input", "")),
            ticker_normalized=str(data.get("ticker_normalized", "")),
            asset_type=str(data.get("asset_type", "")),
            category=str(data.get("category", "")),
            metric_name=str(data.get("metric_name", "")),
            value_raw=str(data.get("value_raw", "")),
            value_normalized=quantize_decimal(data.get("value_normalized")),
            unit_raw=str(data.get("unit_raw", "")),
            unit_normalized=data.get("unit_normalized"),
            source_name=str(data.get("source_name", "")),
            source_ref=str(data.get("source_ref", "")),
            observed_at=data.get("observed_at"),
            fetched_at=data.get("fetched_at"),
            target_date=data.get("target_date"),
            criticality=Criticality(
                data.get("criticality", Criticality.SUPPORTING.value)
            ),
            validation_results=[
                ValidationResult.from_dict(v)
                for v in data.get("validation_results", [])
            ],
            quality_status=QualityStatus(
                data.get("quality_status", QualityStatus.LOW.value)
            ),
            quality_reasons=list(data.get("quality_reasons", [])),
        )


# ---------------------------------------------------------------------------
# EvidenceGroupQuality
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceGroupQuality:
    """Aggregated quality of one category/group of evidence.

    Uses ``HIGH``/``MEDIUM``/``LOW``/``BLOCKED``. Retains the group's
    ``criticality``, its evidence IDs, independent/source counts, and readable
    reason codes consumed by the gate (gate behavior is defined in a later
    step, not here).
    """

    category: str
    quality_status: QualityStatus
    criticality: Criticality
    evidence_ids: list[str]
    source_count: int
    independent_source_count: int
    reason_codes: list[str]
    human_readable_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "quality_status": self.quality_status.value,
            "criticality": self.criticality.value,
            "evidence_ids": list(self.evidence_ids),
            "source_count": self.source_count,
            "independent_source_count": self.independent_source_count,
            "reason_codes": list(self.reason_codes),
            "human_readable_reason": self.human_readable_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceGroupQuality:
        return cls(
            category=str(data.get("category", "")),
            quality_status=QualityStatus(
                data.get("quality_status", QualityStatus.LOW.value)
            ),
            criticality=Criticality(
                data.get("criticality", Criticality.SUPPORTING.value)
            ),
            evidence_ids=list(data.get("evidence_ids", [])),
            source_count=int(data.get("source_count", 0)),
            independent_source_count=int(data.get("independent_source_count", 0)),
            reason_codes=list(data.get("reason_codes", [])),
            human_readable_reason=str(data.get("human_readable_reason", "")),
        )


# ---------------------------------------------------------------------------
# GateDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDecision:
    """The gate's verdict and the routing it implies.

    ``decision`` is one of ``normal`` / ``degraded`` / ``blocked``. ``blocked``
    skips the debate and routes to a restricted Research Manager summary;
    ``degraded`` carries limitations and a confidence cap. ``group_statuses``
    holds one :class:`EvidenceGroupQuality` per evaluated category. Fields
    mirror the authoritative gate output; gate behavior is a later step.
    """

    decision: GateVerdict
    decided_at: str
    group_statuses: list[EvidenceGroupQuality]
    critical_evidence_ids: list[str]
    limitations: list[str]
    reason_codes: list[str]
    human_readable_reason: str
    policy_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "decided_at": self.decided_at,
            "group_statuses": [g.to_dict() for g in self.group_statuses],
            "critical_evidence_ids": list(self.critical_evidence_ids),
            "limitations": list(self.limitations),
            "reason_codes": list(self.reason_codes),
            "human_readable_reason": self.human_readable_reason,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateDecision:
        return cls(
            decision=GateVerdict(
                data.get("decision", GateVerdict.NORMAL.value)
            ),
            decided_at=str(data.get("decided_at", "")),
            group_statuses=[
                EvidenceGroupQuality.from_dict(g)
                for g in data.get("group_statuses", [])
            ],
            critical_evidence_ids=list(data.get("critical_evidence_ids", [])),
            limitations=list(data.get("limitations", [])),
            reason_codes=list(data.get("reason_codes", [])),
            human_readable_reason=str(data.get("human_readable_reason", "")),
            policy_version=str(data.get("policy_version", "")),
        )
