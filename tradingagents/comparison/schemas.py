"""Typed, validated, JSON-safe schemas for the Phase 4A baseline comparison.

Design rules (authoritative):

- Every record is a frozen dataclass with exactly the documented fields. JSON
  in/out goes through ``to_dict``/``from_dict`` only and is acyclic and
  deterministic (``sort_keys`` on write).
- **Case identity** (:class:`CaseIdentity`) is the shared, validated quadruple
  ``(ticker, target_date, evidence_snapshot_id, policy_version)`` that both the
  fixed-round baseline and the dynamic policy must match exactly. A mismatch
  fails closed with :class:`PairingError` — the runner will not compare two
  results that are not provably the same case.
- **Measured vs estimated**: ``elapsed_seconds``, ``input_tokens``,
  ``output_tokens``, ``total_tokens``, ``llm_calls`` are *measured* values.
  When a provider did not report them, the caller records the deterministic
  char-based estimate and sets the ``estimated`` flag; the model never labels an
  estimate as measured. Wall-clock observations may be recorded but tests never
  depend on timing.
- **Human traceability** is a documented rubric with human-entered scores; an
  unscored case stays ``pending`` with ``None`` scores rather than fabricating a
  rating.
- Every ratio has an explicit denominator and a documented zero-denominator
  behavior (``None``), enforced by the formula functions in ``metric_formulas``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrategyKey(str, Enum):
    """The two compared strategies.

    ``FIXED`` is the legacy fixed-``max_debate_rounds`` baseline; ``DYNAMIC`` is
    the evidence-aware dynamic termination policy.
    """

    FIXED = "fixed"
    DYNAMIC = "dynamic"


# Human traceability is a documented rubric; these are the fixed, ordered
# dimensions a human may score (each in ``[0, 1]``). An unscored run leaves them
# as ``None`` and the aggregate reports ``pending``. When a result is
# ``SCORED`` it MUST carry exactly ``len(TRACEABILITY_DIMENSIONS)`` non-null
# scores in this exact order (no missing, extra, null, duplicate, or reordered
# dimension) — enforced by ``CaseResult`` and the
# :func:`traceability_scores_for_dimensions` helper.
TRACEABILITY_DIMENSIONS: tuple[str, ...] = (
    "source_attribution",
    "reasoning_clarity",
    "evidence_groundedness",
    "decision_auditability",
)


class TraceabilityStatus(str, Enum):
    PENDING = "pending"
    SCORED = "scored"


# Sentinel stop-reason string for a replayed dynamic run that simply exhausted
# its available scripted rounds without the policy making a genuine termination
# decision. It is NOT an early stop and must never be reported as one (the
# reviewer's correction): it only records that the scripted input was cut short.
INPUT_EXHAUSTED_STOP_REASON = "input_exhausted"


# Stop reasons produced by :func:`evaluate_round` that represent a genuine
# dynamic-policy termination (route != ``continue`` and not the fixed round
# cap). ``max_rounds_reached`` is the cap itself, not an early stop;
# ``input_exhausted`` is not a policy decision at all. Only these reasons
# count toward ``early_stopped``.
_DYNAMIC_STOP_REASONS: frozenset[str] = frozenset(
    {
        "insufficient_evidence",
        "budget_exhausted",
        "no_new_evidence",
        "consensus_reached",
        "diminishing_returns",
    }
)


def traceability_scores_for_dimensions(
    dimension_scores: Mapping[str, float] | Sequence[tuple[str, float]],
) -> list[float]:
    """Build the positional score list for :class:`CaseResult` from a keyed map.

    ``dimension_scores`` maps each traceability dimension (or lists
    ``(dimension, score)`` pairs) to a ``[0, 1]`` score. It MUST name exactly
    the four ``TRACEABILITY_DIMENSIONS``, in that exact order, with no missing,
    extra, duplicate, or reordered dimension — otherwise it raises. This is the
    single contract entry point a human (or a test) uses to record a fully
    scored traceability result, so a malformed score set fails closed rather
    than silently mis-claiming a rating.
    """
    if isinstance(dimension_scores, Mapping):
        items = list(dimension_scores.items())
    else:
        items = list(dimension_scores)
    keys = [str(k) for k, _ in items]
    if len(set(keys)) != len(keys):
        raise ValueError("traceability dimensions must not contain duplicates")
    if set(keys) != set(TRACEABILITY_DIMENSIONS):
        raise ValueError(
            "traceability dimensions must be exactly "
            f"{list(TRACEABILITY_DIMENSIONS)}, got {keys}"
        )
    if keys != list(TRACEABILITY_DIMENSIONS):
        raise ValueError(
            "traceability dimensions must be in TRACEABILITY_DIMENSIONS order, "
            f"got {keys}"
        )
    values = dict(items)
    scored = []
    for dimension in TRACEABILITY_DIMENSIONS:
        score = float(values[dimension])
        if score < 0.0 or score > 1.0:
            raise ValueError(
                f"traceability score for {dimension!r} must be in [0, 1], got {score!r}"
            )
        scored.append(score)
    return scored


@dataclass(frozen=True)
class CaseIdentity:
    """Shared, validated identity for one compared case.

    Both strategies MUST carry the identical ``(ticker, target_date,
    evidence_snapshot_id, policy_version)``. ``evidence_snapshot_id`` pins the
    exact evidence snapshot (e.g. the deterministic ``run_id`` derived from
    ``(trade_date, normalized symbol)`` plus a snapshot revision);
    ``policy_version`` pins the dynamic-policy version so a threshold change is
    never silently compared against an older one.
    """

    ticker: str
    target_date: str
    evidence_snapshot_id: str
    policy_version: str

    def __post_init__(self) -> None:
        for name in ("ticker", "target_date", "evidence_snapshot_id", "policy_version"):
            value = str(getattr(self, name))
            if not value.strip():
                raise ValueError(f"CaseIdentity.{name} must be a non-empty string")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, str]:
        return {
            "ticker": self.ticker,
            "target_date": self.target_date,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseIdentity:
        data = data or {}
        return cls(
            ticker=str(data.get("ticker", "")),
            target_date=str(data.get("target_date", "")),
            evidence_snapshot_id=str(data.get("evidence_snapshot_id", "")),
            policy_version=str(data.get("policy_version", "")),
        )

    def matches(self, other: CaseIdentity) -> bool:
        """True iff every identity field is identical (no tolerance)."""
        return (
            self.ticker == other.ticker
            and self.target_date == other.target_date
            and self.evidence_snapshot_id == other.evidence_snapshot_id
            and self.policy_version == other.policy_version
        )


class PairingError(ValueError):
    """Raised when two results do not share the exact same case identity.

    Fail closed: the comparison runner never compares two cases it cannot prove
    are the same ``(ticker, target_date, evidence_snapshot_id, policy_version)``.
    """


@dataclass(frozen=True)
class CaseResult:
    """Measured + estimated outcome of running ONE strategy on ONE case.

    ``identity`` MUST be identical between the fixed and dynamic pair. All
    counters are validated non-negative. The ``estimated`` flag records whether
    the token/time values were derived by the deterministic char-based
    estimator (``True``) or reported exactly by the provider (``False``).
    ``strong_conclusion`` is an explicit machine-readable flag; the
    false-strong-conclusion metric is derived from it plus the gate/quality
    outcome, never inferred from prose.

    ``early_stopped`` is ``True`` ONLY when the dynamic policy made a genuine
    termination decision (a real stop reason) before the hard round cap. A run
    that merely exhausts its available scripted rounds (input exhaustion) is
    ``early_stopped == False`` and records
    ``stop_reason == INPUT_EXHAUSTED_STOP_REASON`` — never a dynamic early stop.
    ``stop_reason`` is the *actual* deterministic reason the run stopped (the
    evaluator's ``StopReason.value`` for a genuine stop, ``max_rounds_reached``
    for the fixed cap, ``input_exhausted`` when the scripted input ran out, or
    ``""`` when no round executed); the generic label is never substituted, so
    the decision stays auditable.
    """

    strategy: StrategyKey
    identity: CaseIdentity
    # --- measured usage ---
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    elapsed_seconds: float = 0.0
    # --- debate structure ---
    debate_rounds: int = 0
    early_stopped: bool = False
    stop_reason: str = ""
    # --- evidence / quality ---
    valid_cited_evidence_ids: list[str] = field(default_factory=list)
    total_eligible_evidence_ids: int = 0
    strong_conclusion: bool = False
    gate_verdict: str = ""  # "normal" | "degraded" | "blocked" | ""
    quality_status: str = ""  # "High" | "Medium" | "Low" | "Blocked" | ""
    # --- estimated vs measured ---
    estimated: bool = False
    # --- human traceability (pending until a human scores it) ---
    traceability_scores: list[float | None] = field(default_factory=list)
    traceability_status: TraceabilityStatus = TraceabilityStatus.PENDING

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategyKey):
            object.__setattr__(self, "strategy", StrategyKey(str(self.strategy)))
        if not isinstance(self.identity, CaseIdentity):
            object.__setattr__(self, "identity", CaseIdentity.from_dict(dict(self.identity)))
        for name in ("llm_calls", "tool_calls", "input_tokens", "output_tokens",
                     "total_tokens", "debate_rounds", "total_eligible_evidence_ids"):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"CaseResult.{name} must be >= 0")
            object.__setattr__(self, name, value)
        if self.elapsed_seconds < 0:
            raise ValueError("CaseResult.elapsed_seconds must be >= 0")
        if not isinstance(self.early_stopped, bool):
            object.__setattr__(self, "early_stopped", bool(self.early_stopped))
        if not isinstance(self.strong_conclusion, bool):
            object.__setattr__(self, "strong_conclusion", bool(self.strong_conclusion))
        if not isinstance(self.estimated, bool):
            object.__setattr__(self, "estimated", bool(self.estimated))
        object.__setattr__(self, "stop_reason", str(self.stop_reason or ""))
        object.__setattr__(
            self, "valid_cited_evidence_ids",
            [str(x) for x in (self.valid_cited_evidence_ids or [])],
        )
        object.__setattr__(self, "gate_verdict", str(self.gate_verdict or ""))
        object.__setattr__(self, "quality_status", str(self.quality_status or ""))
        if not isinstance(self.traceability_status, TraceabilityStatus):
            object.__setattr__(
                self, "traceability_status",
                TraceabilityStatus(str(self.traceability_status)),
            )
        scores = list(self.traceability_scores or [])
        clean: list[float | None] = []
        for score in scores:
            if score is None:
                clean.append(None)
                continue
            value = float(score)
            if value < 0.0 or value > 1.0:
                raise ValueError(f"traceability score must be in [0, 1], got {score!r}")
            clean.append(value)
        if self.traceability_status == TraceabilityStatus.SCORED:
            # A scored result must have exactly one non-null score per
            # TRACEABILITY_DIMENSION, in that positional order. Missing, extra,
            # null, or reordered dimensions are rejected (fail closed) rather
            # than silently mis-reporting a rating. A SCORED result with an
            # unknown-shape score set raises; a PENDING result keeps any shape
            # (it is unscored and reports no mean).
            if len(clean) != len(TRACEABILITY_DIMENSIONS):
                raise ValueError(
                    "a scored traceability result requires exactly "
                    f"{len(TRACEABILITY_DIMENSIONS)} scores (one per "
                    f"{TRACEABILITY_DIMENSIONS} dimension), got {len(clean)}"
                )
            if any(score is None for score in clean):
                raise ValueError(
                    "a scored traceability result requires a non-null score for "
                    "every TRACEABILITY_DIMENSION"
                )
        object.__setattr__(self, "traceability_scores", clean)
        # --- fail-closed strategy / early_stopped / stop_reason consistency ---
        # A contradictory combination must never be accepted, because the
        # aggregate and report silently propagate ``early_stop_rate`` / the
        # ``early-stopped`` label from ``early_stopped`` without re-validating
        # it. We reject here, as early as possible, using the single genuine-
        # dynamic-stop-reason allowlist shared with the evaluator conventions.
        if self.early_stopped:
            if self.strategy != StrategyKey.DYNAMIC:
                raise ValueError(
                    "only a DYNAMIC strategy result may be early_stopped; a "
                    f"{self.strategy.value!r} result claiming an early stop is "
                    "contradictory"
                )
            if not self.stop_reason:
                raise ValueError(
                    "an early_stopped DYNAMIC result must carry a genuine "
                    "dynamic stop reason, got an empty stop_reason"
                )
            if self.stop_reason not in _DYNAMIC_STOP_REASONS:
                raise ValueError(
                    f"stop_reason {self.stop_reason!r} is not a genuine dynamic "
                    "early-stop reason and cannot be reported as early_stopped; "
                    f"expected one of {sorted(_DYNAMIC_STOP_REASONS)}"
                )

    @property
    def summary_token_total(self) -> int:
        """Authoritative total-token figure: ``total_tokens``.

        ``input_tokens + output_tokens`` is kept as a cross-check only; a
        provider reporting a single total wins.
        """
        return self.total_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "identity": self.identity.to_dict(),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "debate_rounds": self.debate_rounds,
            "early_stopped": self.early_stopped,
            "stop_reason": self.stop_reason,
            "valid_cited_evidence_ids": list(self.valid_cited_evidence_ids),
            "total_eligible_evidence_ids": self.total_eligible_evidence_ids,
            "strong_conclusion": self.strong_conclusion,
            "gate_verdict": self.gate_verdict,
            "quality_status": self.quality_status,
            "estimated": self.estimated,
            "traceability_status": self.traceability_status.value,
            "traceability_scores": list(self.traceability_scores),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseResult:
        data = data or {}
        return cls(
            strategy=StrategyKey(data.get("strategy", StrategyKey.DYNAMIC.value)),
            identity=CaseIdentity.from_dict(data.get("identity", {})),
            llm_calls=int(data.get("llm_calls", 0)),
            tool_calls=int(data.get("tool_calls", 0)),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            elapsed_seconds=float(data.get("elapsed_seconds", 0.0)),
            debate_rounds=int(data.get("debate_rounds", 0)),
            early_stopped=bool(data.get("early_stopped", False)),
            stop_reason=str(data.get("stop_reason", "")),
            valid_cited_evidence_ids=list(data.get("valid_cited_evidence_ids", [])),
            total_eligible_evidence_ids=int(data.get("total_eligible_evidence_ids", 0)),
            strong_conclusion=bool(data.get("strong_conclusion", False)),
            gate_verdict=str(data.get("gate_verdict", "")),
            quality_status=str(data.get("quality_status", "")),
            estimated=bool(data.get("estimated", False)),
            traceability_status=TraceabilityStatus(
                data.get("traceability_status", TraceabilityStatus.PENDING.value)
            ),
            traceability_scores=list(data.get("traceability_scores", [])),
        )

    def as_aggregate(self) -> CaseAggregate:
        """Derive the per-case aggregate metrics from this result's values."""
        from tradingagents.comparison.metric_formulas import (
            compute_case_aggregate,
        )

        return compute_case_aggregate(self)


@dataclass(frozen=True)
class CaseAggregate:
    """Per-case derived metrics for one strategy, computed from formulas.

    These are *derived* values, never raw inputs. Numerators/denominators are
    explicit; a zero denominator yields ``None`` (documented, not fabricated).
    """

    identity: CaseIdentity
    strategy: StrategyKey
    # measured / derived
    llm_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    elapsed_seconds: float
    debate_rounds: int
    early_stop_rate: float | None  # early_stopped / 1 (0.0 or 1.0)
    evidence_citation_coverage: float | None  # valid_cited / total_eligible
    false_strong_conclusion_rate: float | None  # false_strong / strong_count
    strong_conclusion_count: int
    false_strong_conclusion_count: int
    traceability_mean: float | None  # mean of human scores (None if pending)
    traceability_status: TraceabilityStatus
    # Usage provenance: True iff the token/time values were derived by the
    # deterministic char-based estimator (never presented as measured); a
    # per-case indicator so an estimate is never silently labelled measured.
    tool_usage_estimated: bool = False
    consumed_calls_label: str = ""
    # The actual deterministic stop reason (e.g. no_new_evidence,
    # budget_exhausted, max_rounds_reached, input_exhausted) so the
    # termination decision stays auditable; empty when no round executed.
    stop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "strategy": self.strategy.value,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "elapsed_seconds": self.elapsed_seconds,
            "debate_rounds": self.debate_rounds,
            "early_stop_rate": self.early_stop_rate,
            "evidence_citation_coverage": self.evidence_citation_coverage,
            "false_strong_conclusion_rate": self.false_strong_conclusion_rate,
            "strong_conclusion_count": self.strong_conclusion_count,
            "false_strong_conclusion_count": self.false_strong_conclusion_count,
            "traceability_mean": self.traceability_mean,
            "traceability_status": self.traceability_status.value,
            "tool_usage_estimated": self.tool_usage_estimated,
            "consumed_calls_label": self.consumed_calls_label,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseAggregate:
        data = data or {}
        return cls(
            identity=CaseIdentity.from_dict(data.get("identity", {})),
            strategy=StrategyKey(data.get("strategy", StrategyKey.DYNAMIC.value)),
            llm_calls=int(data.get("llm_calls", 0)),
            tool_calls=int(data.get("tool_calls", 0)),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            elapsed_seconds=float(data.get("elapsed_seconds", 0.0)),
            debate_rounds=int(data.get("debate_rounds", 0)),
            early_stop_rate=_opt_float(data.get("early_stop_rate")),
            evidence_citation_coverage=_opt_float(data.get("evidence_citation_coverage")),
            false_strong_conclusion_rate=_opt_float(data.get("false_strong_conclusion_rate")),
            strong_conclusion_count=int(data.get("strong_conclusion_count", 0)),
            false_strong_conclusion_count=int(data.get("false_strong_conclusion_count", 0)),
            traceability_mean=_opt_float(data.get("traceability_mean")),
            traceability_status=TraceabilityStatus(
                data.get("traceability_status", TraceabilityStatus.PENDING.value)
            ),
            tool_usage_estimated=bool(data.get("tool_usage_estimated", False)),
            consumed_calls_label=str(data.get("consumed_calls_label", "")),
            stop_reason=str(data.get("stop_reason", "")),
        )


@dataclass(frozen=True)
class ComparisonReport:
    """Aggregated comparison of FIXED vs DYNAMIC across the paired cases.

    ``paired_cases`` is the ordered list of matched ``(identity, fixed_agg,
    dynamic_agg)``. ``total_cases`` and the per-strategy sums/means are derived
    deterministically; a ratio spanning multiple cases uses the explicit
    per-denominator formula and yields ``None`` when the denominator is zero.
    """

    total_cases: int
    paired_cases: list[tuple[CaseIdentity, CaseAggregate, CaseAggregate]] = field(
        default_factory=list
    )
    fixed_total_llm_calls: int = 0
    dynamic_total_llm_calls: int = 0
    fixed_total_tool_calls: int = 0
    dynamic_total_tool_calls: int = 0
    fixed_total_tokens: int = 0
    dynamic_total_tokens: int = 0
    fixed_total_time: float = 0.0
    dynamic_total_time: float = 0.0
    fixed_total_rounds: int = 0
    dynamic_total_rounds: int = 0
    fixed_early_stop_count: int = 0
    dynamic_early_stop_count: int = 0
    dynamic_early_stop_rate: float | None = None
    fixed_false_strong_count: int = 0
    dynamic_false_strong_count: int = 0
    fixed_false_strong_rate: float | None = None
    dynamic_false_strong_rate: float | None = None
    # Honest usage-provenance status: how many cases used estimated (vs
    # measured) token/time values, per strategy. Zero means fully measured;
    # N (== total_cases) means every case was estimated.
    fixed_estimated_cases: int = 0
    dynamic_estimated_cases: int = 0
    # Per-strategy counts of the actual stop reason each case reached, so the
    # aggregate preserves (not re-labels) the termination decision. Keys are the
    # deterministic stop-reason strings; an absent key means zero occurrences.
    fixed_stop_reasons: dict[str, int] = field(default_factory=dict)
    dynamic_stop_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "paired_cases": [
                {
                    "identity": identity.to_dict(),
                    "fixed": fixed.to_dict(),
                    "dynamic": dynamic.to_dict(),
                }
                for identity, fixed, dynamic in self.paired_cases
            ],
            "sums_and_rates": {
                "fixed_total_llm_calls": self.fixed_total_llm_calls,
                "dynamic_total_llm_calls": self.dynamic_total_llm_calls,
                "fixed_total_tool_calls": self.fixed_total_tool_calls,
                "dynamic_total_tool_calls": self.dynamic_total_tool_calls,
                "fixed_total_tokens": self.fixed_total_tokens,
                "dynamic_total_tokens": self.dynamic_total_tokens,
                "fixed_total_time": self.fixed_total_time,
                "dynamic_total_time": self.dynamic_total_time,
                "fixed_total_rounds": self.fixed_total_rounds,
                "dynamic_total_rounds": self.dynamic_total_rounds,
                "fixed_early_stop_count": self.fixed_early_stop_count,
                "dynamic_early_stop_count": self.dynamic_early_stop_count,
                "dynamic_early_stop_rate": self.dynamic_early_stop_rate,
                "fixed_false_strong_count": self.fixed_false_strong_count,
                "dynamic_false_strong_count": self.dynamic_false_strong_count,
                "fixed_false_strong_rate": self.fixed_false_strong_rate,
                "dynamic_false_strong_rate": self.dynamic_false_strong_rate,
                "fixed_estimated_cases": self.fixed_estimated_cases,
                "dynamic_estimated_cases": self.dynamic_estimated_cases,
                "fixed_stop_reasons": dict(self.fixed_stop_reasons),
                "dynamic_stop_reasons": dict(self.dynamic_stop_reasons),
            },
        }


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
