"""Deterministic Debate Evaluator for Phase 3B dynamic termination.

The evaluator runs only after a completed Bull + Bear round and applies, in
this exact order, the authoritative decision rules:

1. Critical evidence/gate becomes Blocked -> ``stop`` / ``insufficient_evidence``.
2. Summary reserve cannot be guaranteed, or a token/time/call hard limit is
   reached -> ``summarize`` / ``budget_exhausted``.
3. ``max_debate_rounds`` reached -> ``summarize`` / ``max_rounds_reached``.
4. Both sides produced zero new valid evidence for the completed round
   (respecting ``no_new_evidence_patience``) -> ``summarize`` / ``no_new_evidence``.
5. No critical/major open conflict and stances are close -> ``summarize`` /
   ``consensus_reached``.
6. New High/Medium evidence exists, a critical/major conflict remains, and
   budget permits -> ``continue`` / ``continue_for_new_evidence``.
7. A critical/major interpretive conflict remains, there is material stance
   change, and budget permits -> ``continue`` / ``continue_for_material_change``.
8. Otherwise -> ``summarize`` / ``diminishing_returns``.

The evaluator is pure (no LLM, no network); the LangGraph node factory wraps it
and reads the gate-manifest / turn state off the ``AgentState``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.evidence_manifest import (
    EvidenceManifest,
    collect_valid_new_evidence,
)
from tradingagents.debate.models import (
    BudgetState,
    ConflictKind,
    ConflictSeverity,
    ConflictStatus,
    DebateRoute,
    DecisionTraceEntry,
    RoundMetrics,
    RoutingDecision,
    Stance,
    StopReason,
    stance_value,
)

# Standardised rule identifiers (stable; consumed by the decision trace).
RULE_GATE_BLOCKED = "gate_blocked"
RULE_BUDGET = "budget"
RULE_MAX_ROUNDS = "max_rounds"
RULE_NO_NEW_EVIDENCE = "no_new_evidence"
RULE_CONSENSUS = "consensus"
RULE_CONTINUE_NEW_EVIDENCE = "continue_new_evidence"
RULE_CONTINUE_MATERIAL = "continue_material"
RULE_DIMINISHING = "diminishing_returns"

_BULL = "Bull"
_BEAR = "Bear"


def _rating_distance(a: Stance, b: Stance) -> int:
    return abs(stance_value(a) - stance_value(b))


def _confidence_distance(a: float, b: float) -> float:
    return abs(a - b)


def _next_speaker_after(bear_turn: Any) -> str:
    """The speaker whose turn opens the next round (the opener alternates)."""
    return _BULL


def stances_close(
    *,
    stance_a: Stance,
    confidence_a: float,
    stance_b: Stance,
    confidence_b: float,
    config: DebateTerminationConfig,
) -> bool:
    """True iff ratings *and* confidence are both within validated thresholds."""
    return (
        _rating_distance(stance_a, stance_b) <= config.stance_distance_threshold
        and _confidence_distance(confidence_a, confidence_b)
        <= config.confidence_delta_threshold
    )


def is_material_stance_change(
    *,
    prior_stance: Stance | None,
    prior_confidence: float | None,
    prior_evidence_ids: Sequence[str],
    prior_reasons: Sequence[str],
    current_stance: Stance,
    current_confidence: float,
    current_evidence_ids: Sequence[str],
    current_reasons: Sequence[str],
    config: DebateTerminationConfig,
) -> bool:
    """Material change: rating changed, confidence changed beyond threshold, or
    the core evidence/reason set changed. Rephrasing alone is not material."""
    if prior_stance is None:
        return False
    if prior_stance != current_stance:
        return True
    if prior_confidence is not None and (
        _confidence_distance(prior_confidence, current_confidence)
        > config.confidence_delta_threshold
    ):
        return True
    if set(prior_evidence_ids) != set(current_evidence_ids):
        return True
    return set(prior_reasons) != set(current_reasons)


def _repetition_signal(
    *,
    new_valid_evidence_ids: list[str],
    prior_stance: Stance | None,
    current_stance: Stance,
    prior_core_reasons: Sequence[str],
    current_core_reasons: Sequence[str],
) -> bool:
    """Signal that nothing new was added: no valid evidence and the stance is
    unchanged with the same core-reason set (rephrasing only)."""
    if new_valid_evidence_ids:
        return False
    if prior_stance is not None and prior_stance != current_stance:
        return False
    return set(prior_core_reasons) == set(current_core_reasons)


@dataclass(frozen=True)
class _SideReference:
    """Prior round reference for one speaker (Bull or Bear), for change checks.

    ``stance``/``confidence`` are ``None`` when there is no earlier round for
    that speaker (the first completed round), in which case a material-change
    comparison is impossible and correctly returns ``False``.
    """

    stance: Stance | None = None
    confidence: float | None = None
    evidence_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stance is not None and not isinstance(self.stance, Stance):
            object.__setattr__(self, "stance", Stance(str(self.stance)))
        if self.confidence is not None:
            object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "evidence_ids", list(self.evidence_ids or []))
        object.__setattr__(self, "reasons", list(self.reasons or []))


def _open_blocking_conflicts(conflicts: Sequence[Any]) -> int:
    """Count of open critical/major conflicts that must keep debate alive."""
    return sum(1 for c in conflicts if getattr(c, "blocks_termination", lambda: False)())


def _round_new_evidence(
    *,
    round_turns: Sequence[Any],
    previously_cited: set[str],
    manifest: EvidenceManifest,
    target_date: str | None,
    manifest_index: dict[str, str] | None,
) -> list[str]:
    """New valid evidence discovered across a completed round (both sides).

    Only IDs **explicitly linked to a new claim** (``eligible_ids``) can count
    as new. An ID that merely appears in a turn's cited list but is not linked
    to a claim never counts (rule 3 — fail closed on the linkage).
    """
    round_cited: list[str] = []
    linked: list[str] = []
    for turn in round_turns:
        round_cited.extend(turn.cited_evidence_ids)
        linked.extend(turn.linked_evidence_ids())
    new_ids, _ = collect_valid_new_evidence(
        cited_ids=round_cited,
        previously_cited=previously_cited,
        manifest=manifest,
        target_date=target_date,
        eligible_ids=linked,
        evidence_manifest_index=manifest_index,
    )
    return new_ids


def _gate_is_blocked(
    *,
    verdict: str | None,
    group_statuses: Sequence[Mapping[str, Any]],
) -> bool:
    """True iff the gate is blocked (rule 1), or a critical group is Blocked."""
    if verdict == "blocked":
        return True
    for group in group_statuses or []:
        if not isinstance(group, Mapping):
            continue
        if str(group.get("quality_status", "")) == "Blocked" and str(
            group.get("criticality", "")
        ) == "critical":
            return True
    return False


def _build_budget_state(
    config: DebateTerminationConfig,
    usage: Mapping[str, Any],
) -> BudgetState:
    return BudgetState(
        max_calls=config.max_calls,
        max_tokens=config.max_tokens,
        max_time=config.max_time,
        used_calls=int(usage.get("calls", 0)),
        used_tokens=int(usage.get("tokens", 0)),
        used_time=float(usage.get("seconds", 0.0)),
        max_debate_rounds=config.max_debate_rounds,
        reserved_summary_tokens=config.reserved_summary_tokens,
        reserved_summary_seconds=config.reserved_summary_seconds,
        next_round_estimate_tokens=config.next_round_estimate_tokens,
        next_round_estimate_seconds=config.next_round_estimate_seconds,
        usage_estimated=bool(usage.get("estimated", False)),
    )


def _round_metrics(
    *,
    round_index: int,
    new_valid_evidence_ids: list[str],
    open_blocking_conflicts: int,
    repetition_signal: bool,
    material_change: bool,
    usage: Mapping[str, Any],
) -> RoundMetrics:
    return RoundMetrics(
        round_index=round_index,
        new_valid_evidence_count=len(new_valid_evidence_ids),
        new_valid_evidence_ids=list(new_valid_evidence_ids),
        unresolved_critical_or_major_conflict_count=open_blocking_conflicts,
        repetition_signal=repetition_signal,
        material_stance_change=material_change,
        calls=int(usage.get("calls", 0)),
        tokens=int(usage.get("tokens", 0)),
        elapsed_time=float(usage.get("seconds", 0.0)),
        estimated=bool(usage.get("estimated", False)),
    )


def evaluate_round(
    *,
    round_index: int,
    round_turns: Sequence[Any],
    previously_cited: set[str],
    manifest: EvidenceManifest,
    target_date: str | None,
    conflicts: Sequence[Any],
    bull_stance: Stance,
    bear_stance: Stance,
    bull_confidence: float,
    bear_confidence: float,
    config: DebateTerminationConfig,
    usage: Mapping[str, Any],
    gate_verdict: str | None = None,
    gate_group_statuses: Sequence[Mapping[str, Any]] | None = None,
    manifest_index: dict[str, str] | None = None,
    prior_no_new_evidence_streak: int = 0,
    prior_bull: _SideReference | None = None,
    prior_bear: _SideReference | None = None,
    bull_evidence_ids: Sequence[str] = (),
    bull_reasons: Sequence[str] = (),
    bear_evidence_ids: Sequence[str] = (),
    bear_reasons: Sequence[str] = (),
) -> tuple[RoundMetrics, RoutingDecision]:
    """Apply the authoritative decision rules in exact order.

    Returns ``(round_metrics, routing_decision)``. Pure and deterministic given
    its inputs; it never calls an LLM or the network.
    """
    budget = _build_budget_state(config, usage)

    new_valid = _round_new_evidence(
        round_turns=round_turns,
        previously_cited=previously_cited,
        manifest=manifest,
        target_date=target_date,
        manifest_index=manifest_index,
    )
    open_blocking = _open_blocking_conflicts(conflicts)
    # Material change is judged per side against that side's own prior round
    # (Bull->Bull and Bear->Bear), never across differently-speaking turns. A
    # change is material when the rating moved, confidence moved beyond the
    # threshold, or the core evidence/reason set changed. Comparing each side to
    # its own prior round and to nothing else means an unchanged side never
    # looks "material" merely because a different speaker moved, and an
    # action-only divergence is not material by itself.
    bull_material = is_material_stance_change(
        prior_stance=prior_bull.stance if prior_bull else None,
        prior_confidence=prior_bull.confidence if prior_bull else None,
        prior_evidence_ids=prior_bull.evidence_ids if prior_bull else (),
        prior_reasons=prior_bull.reasons if prior_bull else (),
        current_stance=bull_stance,
        current_confidence=bull_confidence,
        current_evidence_ids=bull_evidence_ids,
        current_reasons=bull_reasons,
        config=config,
    )
    bear_material = is_material_stance_change(
        prior_stance=prior_bear.stance if prior_bear else None,
        prior_confidence=prior_bear.confidence if prior_bear else None,
        prior_evidence_ids=prior_bear.evidence_ids if prior_bear else (),
        prior_reasons=prior_bear.reasons if prior_bear else (),
        current_stance=bear_stance,
        current_confidence=bear_confidence,
        current_evidence_ids=bear_evidence_ids,
        current_reasons=bear_reasons,
        config=config,
    )
    material_change = bull_material or bear_material
    repetition = _repetition_signal(
        new_valid_evidence_ids=new_valid,
        prior_stance=prior_bull.stance if prior_bull else None,
        current_stance=bull_stance,
        prior_core_reasons=prior_bull.reasons if prior_bull else (),
        current_core_reasons=bull_reasons,
    )
    metrics = _round_metrics(
        round_index=round_index,
        new_valid_evidence_ids=new_valid,
        open_blocking_conflicts=open_blocking,
        repetition_signal=repetition,
        material_change=material_change,
        usage=usage,
    )

    trace: list[DecisionTraceEntry] = []

    # Rule 1: critical evidence/gate becomes Blocked -> stop.
    gate_blocked = _gate_is_blocked(
        verdict=gate_verdict, group_statuses=gate_group_statuses or []
    )
    trace.append(DecisionTraceEntry(
        rule=RULE_GATE_BLOCKED,
        activated=gate_blocked,
        thresholds={"verdict": gate_verdict or ""},
        actual={"gate_blocked": gate_blocked},
        evidence_ids=[],
    ))
    if gate_blocked:
        return metrics, RoutingDecision(
            route=DebateRoute.STOP,
            stop_reason=StopReason.INSUFFICIENT_EVIDENCE,
            next_speaker="",
            round_index=round_index,
            trace=trace,
        )

    # Rule 2: budget reserve / hard limit -> summarize.
    summary_safe = budget.summary_reserve_guaranteed(
        tokens=budget.next_round_estimate_tokens,
        seconds=budget.next_round_estimate_seconds,
    )
    hard_limit = budget.hard_limit_reached()
    budget_exhausted = (not summary_safe) or hard_limit
    trace.append(DecisionTraceEntry(
        rule=RULE_BUDGET,
        activated=budget_exhausted,
        thresholds={
            "max_calls": budget.max_calls,
            "max_tokens": budget.max_tokens,
            "max_time": budget.max_time,
            "reserved_summary_tokens": budget.reserved_summary_tokens,
            "reserved_summary_seconds": budget.reserved_summary_seconds,
            "next_round_estimate_tokens": budget.next_round_estimate_tokens,
            "next_round_estimate_seconds": budget.next_round_estimate_seconds,
        },
        actual={
            "used_calls": budget.used_calls,
            "used_tokens": budget.used_tokens,
            "used_time": budget.used_time,
            "summary_safe": summary_safe,
            "hard_limit_reached": hard_limit,
        },
        evidence_ids=[],
    ))
    if budget_exhausted:
        return metrics, RoutingDecision(
            route=DebateRoute.SUMMARIZE,
            stop_reason=StopReason.BUDGET_EXHAUSTED,
            next_speaker="",
            round_index=round_index,
            trace=trace,
        )

    # Rule 3: max_debate_rounds reached -> summarize (outranks no-new-evidence).
    max_rounds_reached = round_index >= config.max_debate_rounds
    trace.append(DecisionTraceEntry(
        rule=RULE_MAX_ROUNDS,
        activated=max_rounds_reached,
        thresholds={"max_debate_rounds": config.max_debate_rounds},
        actual={"round_index": round_index},
        evidence_ids=[],
    ))
    if max_rounds_reached:
        return metrics, RoutingDecision(
            route=DebateRoute.SUMMARIZE,
            stop_reason=StopReason.MAX_ROUNDS_REACHED,
            next_speaker="",
            round_index=round_index,
            trace=trace,
        )

    # Rule 4: both sides zero new valid evidence within patience -> summarize.
    if metrics.new_valid_evidence_count:
        no_new_streak = 0
    else:
        no_new_streak = int(prior_no_new_evidence_streak or 0) + 1
    no_new_evidence = no_new_streak >= config.no_new_evidence_patience
    trace.append(DecisionTraceEntry(
        rule=RULE_NO_NEW_EVIDENCE,
        activated=no_new_evidence,
        thresholds={"no_new_evidence_patience": config.no_new_evidence_patience},
        actual={
            "new_valid_evidence_count": metrics.new_valid_evidence_count,
            "no_new_streak": no_new_streak,
        },
        evidence_ids=list(metrics.new_valid_evidence_ids),
    ))
    if no_new_evidence:
        return metrics, RoutingDecision(
            route=DebateRoute.SUMMARIZE,
            stop_reason=StopReason.NO_NEW_EVIDENCE,
            next_speaker="",
            round_index=round_index,
            trace=trace,
        )

    # Rule 5: no critical/major open conflict and stances close -> consensus.
    close = stances_close(
        stance_a=bull_stance,
        confidence_a=bull_confidence,
        stance_b=bear_stance,
        confidence_b=bear_confidence,
        config=config,
    )
    consensus = open_blocking == 0 and close
    trace.append(DecisionTraceEntry(
        rule=RULE_CONSENSUS,
        activated=consensus,
        thresholds={
            "stance_distance_threshold": config.stance_distance_threshold,
            "confidence_delta_threshold": config.confidence_delta_threshold,
        },
        actual={
            "rating_distance": _rating_distance(bull_stance, bear_stance),
            "confidence_distance": _confidence_distance(bull_confidence, bear_confidence),
            "open_blocking_conflicts": open_blocking,
        },
        evidence_ids=[],
    ))
    if consensus:
        return metrics, RoutingDecision(
            route=DebateRoute.SUMMARIZE,
            stop_reason=StopReason.CONSENSUS_REACHED,
            next_speaker="",
            round_index=round_index,
            trace=trace,
        )

    budget_permits = budget.can_run_full_round()
    interpretive_open = any(
        getattr(c, "kind", None) == ConflictKind.INTERPRETIVE
        and getattr(c, "severity", None) in (ConflictSeverity.CRITICAL, ConflictSeverity.MAJOR)
        and getattr(c, "status", None) == ConflictStatus.OPEN
        for c in conflicts
    )

    # Rule 6: new valid evidence + blocking conflict remains + budget -> continue.
    continue_new_evidence = bool(new_valid) and open_blocking > 0 and budget_permits
    trace.append(DecisionTraceEntry(
        rule=RULE_CONTINUE_NEW_EVIDENCE,
        activated=continue_new_evidence,
        thresholds={"budget_permits": budget_permits},
        actual={
            "new_valid_evidence_count": metrics.new_valid_evidence_count,
            "open_blocking_conflicts": open_blocking,
            "budget_permits": budget_permits,
        },
        evidence_ids=list(metrics.new_valid_evidence_ids),
    ))
    if continue_new_evidence:
        return metrics, RoutingDecision(
            route=DebateRoute.CONTINUE,
            stop_reason=StopReason.CONTINUE_FOR_NEW_EVIDENCE,
            next_speaker=_next_speaker_after(round_turns[-1] if round_turns else None),
            round_index=round_index,
            trace=trace,
        )

    # Rule 7: interpretive conflict remains + material change + budget -> continue.
    continue_material = interpretive_open and material_change and budget_permits
    trace.append(DecisionTraceEntry(
        rule=RULE_CONTINUE_MATERIAL,
        activated=continue_material,
        thresholds={"budget_permits": budget_permits},
        actual={
            "interpretive_open": interpretive_open,
            "material_stance_change": material_change,
            "budget_permits": budget_permits,
        },
        evidence_ids=[],
    ))
    if continue_material:
        return metrics, RoutingDecision(
            route=DebateRoute.CONTINUE,
            stop_reason=StopReason.CONTINUE_FOR_MATERIAL_CHANGE,
            next_speaker=_next_speaker_after(round_turns[-1] if round_turns else None),
            round_index=round_index,
            trace=trace,
        )

    # Rule 8: otherwise -> diminishing returns.
    trace.append(DecisionTraceEntry(
        rule=RULE_DIMINISHING,
        activated=True,
        thresholds={},
        actual={"new_valid_evidence_count": metrics.new_valid_evidence_count},
        evidence_ids=[],
    ))
    return metrics, RoutingDecision(
        route=DebateRoute.SUMMARIZE,
        stop_reason=StopReason.DIMINISHING_RETURNS,
        next_speaker="",
        round_index=round_index,
        trace=trace,
    )
