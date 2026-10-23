"""Typed, deterministic, JSON-safe models for Phase 3B dynamic debate termination.

These structures carry the structured metadata the Bull/Bear turns must produce
alongside their readable argument, plus the deterministic bookkeeping the
Debate Evaluator uses to pick whether to continue, summarize, or stop the
debate.

Design rules (authoritative):

- Every model is a frozen dataclass with exactly the fields documented here and
  no extras. ``to_dict``/``from_dict`` are the only serialization surfaces and
  are acyclic (nothing holds an object reference back to its owner beyond a
  string ID), so the values survive LangGraph checkpointing as plain
  JSON-safe primitives.
- Enums use ``str, Enum`` so their stable ``value`` is what serializes.
- Confidence is always in ``[0, 1]``; stance is always one of the five-tier
  scale. Any constructor that receives an out-of-range confidence raises rather
  than silently clamping, so a bad turn is surfaced instead of corrupting the
  decision trace.
- Round metric counters are plain ints/floats; time/token estimates are
  ``float``/``int`` and carry an ``estimated`` flag so usage is never presented
  as exact when the provider did not report it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Stance(str, Enum):
    """The five-tier rating scale (fixed order)."""

    SELL = "Sell"
    UNDERWEIGHT = "Underweight"
    HOLD = "Hold"
    OVERWEIGHT = "Overweight"
    BUY = "Buy"


# Numeric mapping used for distance comparisons (Sell=-2 .. Buy=2).
STANCE_VALUE: dict[Stance, int] = {
    Stance.SELL: -2,
    Stance.UNDERWEIGHT: -1,
    Stance.HOLD: 0,
    Stance.OVERWEIGHT: 1,
    Stance.BUY: 2,
}


def stance_value(stance: Stance) -> int:
    """Numeric value of a stance for distance arithmetic."""
    return STANCE_VALUE[Stance(stance)]


def _coerce_stance(value: Any) -> Stance:
    """Coerce a stance value (enum or string) to a :class:`Stance`.

    Accepts the canonical enum, a case-insensitive label ("buy"), and the
    ``Stance.Buy`` serialized form, so a turn deserialized from a checkpoint or
    built from free text normalizes deterministically instead of raising.
    """
    if isinstance(value, Stance):
        return value
    text = str(value).strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1].strip().lower()
    mapping = {
        "sell": Stance.SELL,
        "underweight": Stance.UNDERWEIGHT,
        "hold": Stance.HOLD,
        "overweight": Stance.OVERWEIGHT,
        "buy": Stance.BUY,
    }
    return mapping.get(text, Stance.HOLD)


class ConflictKind(str, Enum):
    FACTUAL = "factual"
    INTERPRETIVE = "interpretive"
    ACTION = "action"


class ConflictSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class ConflictStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED_TO_MANAGER = "escalated_to_manager"


class ConflictAction(str, Enum):
    """The lifecycle action a turn's structured metadata asserts for a conflict.

    ``ASSERT`` declares a new (or re-observes an existing) conflict with the
    stated topic/claims/evidence; ``RESOLVE`` closes a previously-open conflict;
    ``ESCALATE`` promotes an open conflict to the Research Manager. Only the
    structured marker may carry these — never free-form prose.
    """

    ASSERT = "assert"
    RESOLVE = "resolve"
    ESCALATE = "escalate"


class MetadataParseStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    PARTIAL = "partial"


class DebateRoute(str, Enum):
    CONTINUE = "continue"
    SUMMARIZE = "summarize"
    STOP = "stop"


class StopReason(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_ROUNDS_REACHED = "max_rounds_reached"
    NO_NEW_EVIDENCE = "no_new_evidence"
    CONSENSUS_REACHED = "consensus_reached"
    CONTINUE_FOR_NEW_EVIDENCE = "continue_for_new_evidence"
    CONTINUE_FOR_MATERIAL_CHANGE = "continue_for_material_change"
    DIMINISHING_RETURNS = "diminishing_returns"
    MALFORMED_STATE = "malformed_debate_state"


def _norm_confidence(value: float) -> float:
    """Validate a confidence is in ``[0, 1]``; raise otherwise."""
    confidence = float(value)
    if confidence != confidence or confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"confidence must be in [0, 1], got {value!r}")
    return confidence


def _norm_float(value: Any) -> float:
    """Coerce a non-negative float metric (rejecting NaN/inf)."""
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")) or result < 0:
        raise ValueError(f"expected a non-negative finite metric, got {value!r}")
    return result


@dataclass(frozen=True)
class ClaimEvidenceLink:
    """A single new claim plus the evidence IDs it explicitly cites.

    A new claim only counts as valid new evidence when it is explicitly linked
    to a known, High/Medium, on-or-before-target evidence ID. ``evidence_ids``
    is the bounded set the author linked to this claim; an ID that merely
    appears in the turn's prose or general citation list but is not linked here
    never counts as new.
    """

    claim: str
    evidence_ids: list[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim", str(self.claim))
        object.__setattr__(self, "evidence_ids", list(self.evidence_ids or []))

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimEvidenceLink:
        return cls(
            claim=str(data.get("claim", "")),
            evidence_ids=list(data.get("evidence_ids", [])),
        )


@dataclass(frozen=True)
class DebateTurn:
    """One Bull or Bear turn: readable argument plus structured metadata.

    ``content`` is the natural-language readable argument (the part that is
    always preserved, even when metadata parsing fails). ``stance``,
    ``confidence``, ``cited_evidence_ids``, ``addressed_conflict_ids``,
    ``new_claims``, ``claim_evidence_links``, and ``unresolved_questions`` are
    the structured metadata extracted from the turn. ``metadata_parse_status``
    records whether that extraction succeeded.

    ``claim_evidence_links`` is the authoritative claim-to-evidence linkage
    (rule 3 of valid-new-evidence). An evidence ID counts as new only if it
    appears in one of these links; ``cited_evidence_ids`` alone is never
    sufficient. ``new_claims`` is retained as the ordered claim strings for
    readability and material-change checks.
    """

    speaker: str
    content: str
    stance: Stance
    confidence: float
    cited_evidence_ids: list[str] = field(default_factory=list)
    addressed_conflict_ids: list[str] = field(default_factory=list)
    new_claims: list[str] = field(default_factory=list)
    claim_evidence_links: list[ClaimEvidenceLink] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    conflict_assertions: list[ConflictAssertion] = field(default_factory=list)
    metadata_parse_status: MetadataParseStatus = MetadataParseStatus.OK

    def __post_init__(self) -> None:
        object.__setattr__(self, "speaker", str(self.speaker))
        object.__setattr__(self, "content", str(self.content))
        object.__setattr__(self, "stance", _coerce_stance(self.stance))
        object.__setattr__(self, "confidence", _norm_confidence(self.confidence))
        for list_field in (
            "cited_evidence_ids",
            "addressed_conflict_ids",
            "new_claims",
            "unresolved_questions",
        ):
            object.__setattr__(self, list_field, list(getattr(self, list_field) or []))
        object.__setattr__(
            self,
            "claim_evidence_links",
            list(self.claim_evidence_links or []),
        )
        object.__setattr__(
            self,
            "conflict_assertions",
            list(self.conflict_assertions or []),
        )
        if not isinstance(self.metadata_parse_status, MetadataParseStatus):
            object.__setattr__(
                self, "metadata_parse_status", MetadataParseStatus(str(self.metadata_parse_status))
            )

    def linked_evidence_ids(self) -> list[str]:
        """The bounded, ordered set of evidence IDs explicitly linked to a claim."""
        linked: list[str] = []
        for link in self.claim_evidence_links:
            for aid in link.evidence_ids:
                if aid and aid not in linked:
                    linked.append(aid)
        return linked

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "content": self.content,
            "stance": self.stance.value,
            "confidence": self.confidence,
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "addressed_conflict_ids": list(self.addressed_conflict_ids),
            "new_claims": list(self.new_claims),
            "claim_evidence_links": [link.to_dict() for link in self.claim_evidence_links],
            "unresolved_questions": list(self.unresolved_questions),
            "conflict_assertions": [a.to_dict() for a in self.conflict_assertions],
            "metadata_parse_status": self.metadata_parse_status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateTurn:
        data = data or {}
        return cls(
            speaker=str(data.get("speaker", "")),
            content=str(data.get("content", "")),
            stance=Stance(data.get("stance", Stance.HOLD.value)),
            confidence=float(data.get("confidence", 0.0)),
            cited_evidence_ids=list(data.get("cited_evidence_ids", [])),
            addressed_conflict_ids=list(data.get("addressed_conflict_ids", [])),
            new_claims=list(data.get("new_claims", [])),
            claim_evidence_links=[
                ClaimEvidenceLink.from_dict(link)
                for link in data.get("claim_evidence_links", [])
            ],
            unresolved_questions=list(data.get("unresolved_questions", [])),
            conflict_assertions=[
                ConflictAssertion.from_dict(a)
                for a in data.get("conflict_assertions", [])
            ],
            metadata_parse_status=MetadataParseStatus(
                data.get("metadata_parse_status", MetadataParseStatus.OK.value)
            ),
        )


@dataclass(frozen=True)
class ConflictRecord:
    """One tracked disagreement between the Bull and Bear positions.

    ``kind`` is whether the disagreement is factual, interpretive, or an action
    recommendation; ``severity`` is critical/major/minor; ``status`` is
    open/resolved/escalated_to_manager. Only open critical/major conflicts keep
    a debate alive; resolved and escalated conflicts do not, and action-only
    disagreement belongs to the Research Manager.

    Lifecycle fields (part of the same deterministic, JSON-safe record):

    - ``participants`` is the ordered, deduplicated set of speakers that
      asserted this conflict (typically ``["Bull", "Bear"]``).
    - ``first_seen_round`` / ``last_seen_round`` are the 1-based round indices in
      which this conflict was first asserted and most recently observed.
    - ``resolution_reason`` / ``escalation_reason`` carry the human-readable
      reason a conflict moved to ``resolved`` / ``escalated_to_manager``. A
      resolved/escalated conflict keeps its reason so the Research Manager and
      any report can audit why it stopped blocking the debate.

    All new fields default to safe values so a legacy checkpoint (or a
    manually-constructed record with only the original fields) round-trips
    unchanged — backward compatibility is preserved. A conflict with
    ``participants`` absent defaults to both speakers, since a tracked conflict
    is by construction a Bull/Bear disagreement.
    """

    conflict_id: str
    topic: str
    bull_claim: str
    bear_claim: str
    evidence_ids: list[str] = field(default_factory=list)
    kind: ConflictKind = ConflictKind.INTERPRETIVE
    severity: ConflictSeverity = ConflictSeverity.MAJOR
    status: ConflictStatus = ConflictStatus.OPEN
    participants: list[str] = field(default_factory=lambda: ["Bull", "Bear"])
    first_seen_round: int = 1
    last_seen_round: int = 1
    resolution_reason: str = ""
    escalation_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "conflict_id", str(self.conflict_id))
        object.__setattr__(self, "topic", str(self.topic))
        object.__setattr__(self, "bull_claim", str(self.bull_claim))
        object.__setattr__(self, "bear_claim", str(self.bear_claim))
        object.__setattr__(self, "evidence_ids", list(self.evidence_ids or []))
        if not isinstance(self.kind, ConflictKind):
            object.__setattr__(self, "kind", ConflictKind(str(self.kind)))
        if not isinstance(self.severity, ConflictSeverity):
            object.__setattr__(
                self, "severity", ConflictSeverity(str(self.severity))
            )
        if not isinstance(self.status, ConflictStatus):
            object.__setattr__(self, "status", ConflictStatus(str(self.status)))
        object.__setattr__(self, "participants", list(self.participants or []))
        object.__setattr__(self, "first_seen_round", int(self.first_seen_round))
        object.__setattr__(self, "last_seen_round", int(self.last_seen_round))
        object.__setattr__(self, "resolution_reason", str(self.resolution_reason or ""))
        object.__setattr__(self, "escalation_reason", str(self.escalation_reason or ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "topic": self.topic,
            "bull_claim": self.bull_claim,
            "bear_claim": self.bear_claim,
            "evidence_ids": list(self.evidence_ids),
            "kind": self.kind.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "participants": list(self.participants),
            "first_seen_round": self.first_seen_round,
            "last_seen_round": self.last_seen_round,
            "resolution_reason": self.resolution_reason,
            "escalation_reason": self.escalation_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictRecord:
        data = data or {}
        return cls(
            conflict_id=str(data.get("conflict_id", "")),
            topic=str(data.get("topic", "")),
            bull_claim=str(data.get("bull_claim", "")),
            bear_claim=str(data.get("bear_claim", "")),
            evidence_ids=list(data.get("evidence_ids", [])),
            kind=ConflictKind(data.get("kind", ConflictKind.INTERPRETIVE.value)),
            severity=ConflictSeverity(
                data.get("severity", ConflictSeverity.MAJOR.value)
            ),
            status=ConflictStatus(data.get("status", ConflictStatus.OPEN.value)),
            participants=list(data.get("participants") or ["Bull", "Bear"]),
            first_seen_round=int(data.get("first_seen_round", 1)),
            last_seen_round=int(data.get("last_seen_round", 1)),
            resolution_reason=str(data.get("resolution_reason", "") or ""),
            escalation_reason=str(data.get("escalation_reason", "") or ""),
        )

    def blocks_termination(self) -> bool:
        """True iff this open conflict must keep the debate alive.

        An action-only conflict (``kind == ACTION``) never blocks: the two sides
        recommending different actions belongs to the Research Manager to weigh,
        not to the debate-termination gate (see the evaluator's rule ordering).
        Only an open factual/interpretive critical or major conflict keeps a
        debate alive.
        """
        return (
            self.status == ConflictStatus.OPEN
            and self.kind != ConflictKind.ACTION
            and self.severity in (ConflictSeverity.CRITICAL, ConflictSeverity.MAJOR)
        )


@dataclass(frozen=True)
class ConflictAssertion:
    """One structured conflict declaration/reference carried by a single turn.

    This is the **explicit structured contract** for how a Bull or Bear turn
    asserts, resolves, or escalates a conflict. It is parsed only from the
    ``DEBATE_METADATA`` marker — never from free-form prose and never from
    hidden chain-of-thought. When a turn carries no ``conflict_assertions`` the
    tracker records no new conflict (fail closed on missing metadata).

    ``action`` is one of ``assert`` / ``resolve`` / ``escalate``. An ``assert``
    declares the conflict with its ``topic``, opposing ``bull_claim`` /
    ``bear_claim``, ``kind``, and ``evidence_ids``; a ``resolve`` / ``escalate``
    references an already-tracked conflict by ``conflict_id`` and carries the
    human-readable ``reason``. ``severity`` is recorded on ``assert`` (used to
    build the :class:`ConflictRecord`); on ``resolve``/``escalate`` it is left at
    its default.

    Invalid or future ``evidence_ids`` never create a valid conflict: the
    tracker validates every asserted ID against the gate manifest and the
    target date (fail closed), so an assertion that only names unknown or
    future evidence yields no conflict rather than an unverifiable one.
    """

    action: ConflictAction = ConflictAction.ASSERT
    conflict_id: str = ""
    topic: str = ""
    bull_claim: str = ""
    bear_claim: str = ""
    kind: ConflictKind = ConflictKind.INTERPRETIVE
    severity: ConflictSeverity = ConflictSeverity.MAJOR
    evidence_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.action, ConflictAction):
            object.__setattr__(self, "action", ConflictAction(str(self.action)))
        object.__setattr__(self, "conflict_id", str(self.conflict_id or ""))
        object.__setattr__(self, "topic", str(self.topic or ""))
        object.__setattr__(self, "bull_claim", str(self.bull_claim or ""))
        object.__setattr__(self, "bear_claim", str(self.bear_claim or ""))
        if not isinstance(self.kind, ConflictKind):
            object.__setattr__(self, "kind", ConflictKind(str(self.kind)))
        if not isinstance(self.severity, ConflictSeverity):
            object.__setattr__(
                self, "severity", ConflictSeverity(str(self.severity))
            )
        object.__setattr__(self, "evidence_ids", list(self.evidence_ids or []))
        object.__setattr__(self, "reason", str(self.reason or ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "conflict_id": self.conflict_id,
            "topic": self.topic,
            "bull_claim": self.bull_claim,
            "bear_claim": self.bear_claim,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "evidence_ids": list(self.evidence_ids),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictAssertion:
        data = data or {}
        return cls(
            action=ConflictAction(data.get("action", ConflictAction.ASSERT.value)),
            conflict_id=str(data.get("conflict_id", "") or ""),
            topic=str(data.get("topic", "") or ""),
            bull_claim=str(data.get("bull_claim", "") or ""),
            bear_claim=str(data.get("bear_claim", "") or ""),
            kind=ConflictKind(data.get("kind", ConflictKind.INTERPRETIVE.value)),
            severity=ConflictSeverity(
                data.get("severity", ConflictSeverity.MAJOR.value)
            ),
            evidence_ids=list(data.get("evidence_ids", []) or []),
            reason=str(data.get("reason", "") or ""),
        )


@dataclass(frozen=True)
class ConflictSummary:
    """A safe, structured conflict summary routed to the Research Manager.

    Carries only the auditable fields the manager needs to weigh the debate:
    the open critical/major conflict count, the per-conflict records (id,
    topic, kind, severity, status, participants, seen rounds), and the ordered
    list of resolved/escalated reasons. It never embeds free-form analyst prose
    or chain-of-thought, so the manager receives a deterministic, redacted
    picture of the disagreement rather than a raw debate dump.
    """

    open_blocking_count: int = 0
    conflicts: list[ConflictRecord] = field(default_factory=list)
    resolution_notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_blocking_count", int(self.open_blocking_count))
        object.__setattr__(self, "conflicts", list(self.conflicts or []))
        object.__setattr__(self, "resolution_notes", list(self.resolution_notes or []))

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_blocking_count": self.open_blocking_count,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "resolution_notes": list(self.resolution_notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictSummary:
        data = data or {}
        return cls(
            open_blocking_count=int(data.get("open_blocking_count", 0)),
            conflicts=[
                raw if hasattr(raw, "conflict_id") else ConflictRecord.from_dict(raw)
                for raw in data.get("conflicts", []) or []
            ],
            resolution_notes=list(data.get("resolution_notes", []) or []),
        )

    def to_prompt_block(self) -> str:
        """A short, deterministic, prose-free summary block for the manager prompt.

        Empty when there are no tracked conflicts (only an action-only
        divergence, which is not a blocking conflict), so the manager is not
        fed a fabricated disagreement.
        """
        if not self.conflicts:
            return ""
        lines: list[str] = ["[Tracked debate conflicts]", f"Open blocking conflicts: {self.open_blocking_count}"]
        for c in self.conflicts:
            lines.append(
                f"- {c.conflict_id}: {c.kind.value}/{c.severity.value} "
                f"[{c.status.value}] topic={c.topic} participants={','.join(c.participants or [])} "
                f"rounds={c.first_seen_round}..{c.last_seen_round}"
                + (f" evidence={','.join(c.evidence_ids)}" if c.evidence_ids else "")
            )
        for note in self.resolution_notes:
            lines.append(f"- resolved/escalated: {note}")
        return "\n".join(lines)


@dataclass(frozen=True)
class StanceSnapshot:
    """Ordered five-tier stance plus confidence and the core evidence/reasons."""

    stance: Stance
    confidence: float
    core_evidence_ids: list[str] = field(default_factory=list)
    core_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.stance, Stance):
            object.__setattr__(self, "stance", Stance(str(self.stance)))
        object.__setattr__(self, "confidence", _norm_confidence(self.confidence))
        object.__setattr__(self, "core_evidence_ids", list(self.core_evidence_ids or []))
        object.__setattr__(self, "core_reasons", list(self.core_reasons or []))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stance": self.stance.value,
            "confidence": self.confidence,
            "core_evidence_ids": list(self.core_evidence_ids),
            "core_reasons": list(self.core_reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StanceSnapshot:
        return cls(
            stance=Stance(data.get("stance", Stance.HOLD.value)),
            confidence=float(data.get("confidence", 0.0)),
            core_evidence_ids=list(data.get("core_evidence_ids", [])),
            core_reasons=list(data.get("core_reasons", [])),
        )


@dataclass(frozen=True)
class RoundMetrics:
    """Complete per-round bookkeeping computed by the Debate Evaluator."""

    round_index: int
    new_valid_evidence_count: int
    new_valid_evidence_ids: list[str] = field(default_factory=list)
    unresolved_critical_or_major_conflict_count: int = 0
    repetition_signal: bool = False
    stance_changed: bool = False
    confidence_changed: bool = False
    evidence_set_changed: bool = False
    material_stance_change: bool = False
    calls: int = 0
    tokens: int = 0
    elapsed_time: float = 0.0
    estimated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "round_index", int(self.round_index))
        object.__setattr__(self, "new_valid_evidence_count", int(self.new_valid_evidence_count))
        object.__setattr__(
            self, "new_valid_evidence_ids", list(self.new_valid_evidence_ids or [])
        )
        object.__setattr__(
            self, "unresolved_critical_or_major_conflict_count",
            int(self.unresolved_critical_or_major_conflict_count),
        )
        for bool_field in (
            "repetition_signal",
            "stance_changed",
            "confidence_changed",
            "evidence_set_changed",
            "material_stance_change",
            "estimated",
        ):
            object.__setattr__(self, bool_field, bool(getattr(self, bool_field)))
        object.__setattr__(self, "calls", int(self.calls))
        object.__setattr__(self, "tokens", int(self.tokens))
        object.__setattr__(self, "elapsed_time", _norm_float(self.elapsed_time))

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "new_valid_evidence_count": self.new_valid_evidence_count,
            "new_valid_evidence_ids": list(self.new_valid_evidence_ids),
            "unresolved_critical_or_major_conflict_count": (
                self.unresolved_critical_or_major_conflict_count
            ),
            "repetition_signal": self.repetition_signal,
            "stance_changed": self.stance_changed,
            "confidence_changed": self.confidence_changed,
            "evidence_set_changed": self.evidence_set_changed,
            "material_stance_change": self.material_stance_change,
            "calls": self.calls,
            "tokens": self.tokens,
            "elapsed_time": self.elapsed_time,
            "estimated": self.estimated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoundMetrics:
        return cls(
            round_index=int(data.get("round_index", 0)),
            new_valid_evidence_count=int(data.get("new_valid_evidence_count", 0)),
            new_valid_evidence_ids=list(data.get("new_valid_evidence_ids", [])),
            unresolved_critical_or_major_conflict_count=int(
                data.get("unresolved_critical_or_major_conflict_count", 0)
            ),
            repetition_signal=bool(data.get("repetition_signal", False)),
            stance_changed=bool(data.get("stance_changed", False)),
            confidence_changed=bool(data.get("confidence_changed", False)),
            evidence_set_changed=bool(data.get("evidence_set_changed", False)),
            material_stance_change=bool(data.get("material_stance_change", False)),
            calls=int(data.get("calls", 0)),
            tokens=int(data.get("tokens", 0)),
            elapsed_time=float(data.get("elapsed_time", 0.0)),
            estimated=bool(data.get("estimated", False)),
        )


@dataclass(frozen=True)
class BudgetState:
    """Budget limits, current usage, and the conservative next-round estimate.

    ``max_debate_rounds`` is the hard safety cap on complete rounds.
    ``reserved_summary_tokens``/``reserved_summary_seconds`` are the capacity
    that must always be left for the Research Manager to summarise the debate.
    ``next_round_estimate_tokens``/``next_round_estimate_seconds`` are the
    conservative estimate of one more full Bull+Bear round.
    """

    max_calls: int
    max_tokens: int
    max_time: float
    used_calls: int
    used_tokens: int
    used_time: float
    max_debate_rounds: int
    reserved_summary_tokens: int = 0
    reserved_summary_seconds: float = 0.0
    next_round_estimate_tokens: int = 0
    next_round_estimate_seconds: float = 0.0
    usage_estimated: bool = False

    def __post_init__(self) -> None:
        for int_field in (
            "max_calls", "max_tokens", "max_debate_rounds",
            "reserved_summary_tokens", "next_round_estimate_tokens",
        ):
            object.__setattr__(self, int_field, int(getattr(self, int_field)))
        for float_field in (
            "max_time", "used_time", "reserved_summary_seconds",
            "next_round_estimate_seconds",
        ):
            object.__setattr__(self, float_field, _norm_float(getattr(self, float_field)))
        object.__setattr__(self, "used_calls", int(self.used_calls))
        object.__setattr__(self, "used_tokens", int(self.used_tokens))
        object.__setattr__(self, "usage_estimated", bool(self.usage_estimated))

    def summary_reserve_guaranteed(self, *, tokens: int, seconds: float) -> bool:
        """True iff the summary reserve can still be guaranteed.

        The remaining capacity must cover both the summary reserve and the
        load added by this round so the manager can always conclude the debate.
        """
        remaining_tokens = max(0, self.max_tokens - self.used_tokens)
        remaining_time = max(0.0, self.max_time - self.used_time)
        return (
            remaining_tokens >= self.reserved_summary_tokens + tokens
            and remaining_time >= self.reserved_summary_seconds + seconds
        )

    def call_budget_exhausted(self) -> bool:
        """True iff the call hard limit is reached."""
        return self.used_calls >= self.max_calls

    def token_budget_exhausted(self) -> bool:
        """True iff the token hard limit is reached."""
        return self.used_tokens >= self.max_tokens

    def time_budget_exhausted(self) -> bool:
        """True iff the time hard limit is reached."""
        return self.used_time >= self.max_time

    def hard_limit_reached(self) -> bool:
        """True iff any call/token/time hard limit is reached."""
        return (
            self.call_budget_exhausted()
            or self.token_budget_exhausted()
            or self.time_budget_exhausted()
        )

    def can_run_full_round(self) -> bool:
        """True iff budget permits one more full round plus the summary reserve.

        A full round costs exactly two LLM calls (Bull then Bear), so the call
        check compares the remaining call budget against two — never against a
        token estimate, which is a different unit.
        """
        return (
            not self.hard_limit_reached()
            and self.summary_reserve_guaranteed(
                tokens=self.next_round_estimate_tokens,
                seconds=self.next_round_estimate_seconds,
            )
            and (self.max_calls - self.used_calls) >= 2
            and self.max_debate_rounds > 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "max_time": self.max_time,
            "used_calls": self.used_calls,
            "used_tokens": self.used_tokens,
            "used_time": self.used_time,
            "max_debate_rounds": self.max_debate_rounds,
            "reserved_summary_tokens": self.reserved_summary_tokens,
            "reserved_summary_seconds": self.reserved_summary_seconds,
            "next_round_estimate_tokens": self.next_round_estimate_tokens,
            "next_round_estimate_seconds": self.next_round_estimate_seconds,
            "usage_estimated": self.usage_estimated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetState:
        return cls(
            max_calls=int(data.get("max_calls", 0)),
            max_tokens=int(data.get("max_tokens", 0)),
            max_time=float(data.get("max_time", 0.0)),
            used_calls=int(data.get("used_calls", 0)),
            used_tokens=int(data.get("used_tokens", 0)),
            used_time=float(data.get("used_time", 0.0)),
            max_debate_rounds=int(data.get("max_debate_rounds", 1)),
            reserved_summary_tokens=int(data.get("reserved_summary_tokens", 0)),
            reserved_summary_seconds=float(data.get("reserved_summary_seconds", 0.0)),
            next_round_estimate_tokens=int(data.get("next_round_estimate_tokens", 0)),
            next_round_estimate_seconds=float(data.get("next_round_estimate_seconds", 0.0)),
            usage_estimated=bool(data.get("usage_estimated", False)),
        )


@dataclass(frozen=True)
class DecisionTraceEntry:
    """One deterministic rule evaluation in the decision trace."""

    rule: str
    activated: bool
    thresholds: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "activated": self.activated,
            "thresholds": dict(self.thresholds),
            "actual": dict(self.actual),
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionTraceEntry:
        return cls(
            rule=str(data.get("rule", "")),
            activated=bool(data.get("activated", False)),
            thresholds=dict(data.get("thresholds", {})),
            actual=dict(data.get("actual", {})),
            evidence_ids=list(data.get("evidence_ids", [])),
        )


@dataclass(frozen=True)
class RoutingDecision:
    """Outcome of a Debate Evaluator pass.

    ``route`` is one of ``continue`` / ``summarize`` / ``stop``.
    ``stop_reason`` is the standardized reason string. ``trace`` is the
    deterministic list of rule evaluations that produced this decision.
    """

    route: DebateRoute
    stop_reason: StopReason
    next_speaker: str = ""
    trace: list[DecisionTraceEntry] = field(default_factory=list)
    round_index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.route, DebateRoute):
            object.__setattr__(self, "route", DebateRoute(str(self.route)))
        if not isinstance(self.stop_reason, StopReason):
            object.__setattr__(self, "stop_reason", StopReason(str(self.stop_reason)))
        object.__setattr__(self, "next_speaker", str(self.next_speaker))
        object.__setattr__(self, "trace", list(self.trace or []))
        object.__setattr__(self, "round_index", int(self.round_index))

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "stop_reason": self.stop_reason.value,
            "next_speaker": self.next_speaker,
            "round_index": self.round_index,
            "trace": [entry.to_dict() for entry in self.trace],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingDecision:
        return cls(
            route=DebateRoute(data.get("route", DebateRoute.SUMMARIZE.value)),
            stop_reason=StopReason(data.get("stop_reason", StopReason.DIMINISHING_RETURNS.value)),
            next_speaker=str(data.get("next_speaker", "")),
            round_index=int(data.get("round_index", 0)),
            trace=[DecisionTraceEntry.from_dict(entry) for entry in data.get("trace", [])],
        )
