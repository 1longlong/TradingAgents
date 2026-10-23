"""LangGraph node factory for the Phase 3B Debate Evaluator.

The node runs only after a completed Bull + Bear round (the graph wires
``Bull -> Bear -> Debate Evaluator``). It reads the gate manifest and the
round's structured turns off the state, applies the authoritative decision
rules, and writes a serialized :class:`RoutingDecision` (plus the round metrics
and updated bookkeeping) back to the state.

All dependencies (config, usage snapshot) are injectable so offline tests are
fully deterministic and never touch a live clock or provider.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tradingagents.debate.config import (
    DebateTerminationConfig,
    resolve_debate_termination_config,
)
from tradingagents.debate.conflicts import build_conflict_summary, derive_conflicts
from tradingagents.debate.evaluator import _SideReference, evaluate_round
from tradingagents.debate.evidence_manifest import (
    EvidenceManifest,
    build_evidence_manifest_index,
)
from tradingagents.debate.models import (
    ConflictRecord,
    DebateRoute,
    RoundMetrics,
    RoutingDecision,
    Stance,
    StanceSnapshot,
    StopReason,
)

_EMPTY_STATUSES: list[dict[str, Any]] = []
_EMPTY_RECORDS: list[dict[str, Any]] = []


def _node_name_for_speaker(speaker: str) -> str:
    return ("Bull Researcher" if speaker == "Bull" else "Bear Researcher") if speaker else ""


def _turns_from_state(state: Mapping[str, Any]) -> list[Any]:
    debate = state.get("investment_debate_state") or {}
    turns_raw = debate.get("turns") or []
    # Materialize typed DebateTurn objects from serialized dicts.
    from tradingagents.debate.models import DebateTurn

    result: list[Any] = []
    for raw in turns_raw:
        result.append(
            raw if hasattr(raw, "speaker") else DebateTurn.from_dict(raw)
        )
    return result


def _conflicts_from_state(state: Mapping[str, Any]) -> list[Any]:
    debate = state.get("investment_debate_state") or {}
    conflicts_raw = debate.get("conflicts") or []
    result: list[Any] = []
    for raw in conflicts_raw:
        result.append(
            raw if hasattr(raw, "conflict_id") else ConflictRecord.from_dict(raw)
        )
    return result


def _default_usage_snapshot() -> dict[str, Any]:
    return {"calls": 0, "tokens": 0, "seconds": 0.0, "estimated": False}


def _resolve_usage(
    state: Mapping[str, Any],
    injected_snapshot: Callable[[], Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """The run-level usage the evaluator reads to enforce the budget.

    Prefers the deterministic ``debate_usage`` accrued on the state by the
    Bull/Bear researchers. When it is absent (a bare test state or a legacy
    checkpoint) the injected snapshot is used; when neither exists the usage is
    zeros, which is a real "no calls yet" state, not a disconnected tracker.
    """
    state_usage = state.get("debate_usage")
    if isinstance(state_usage, Mapping) and state_usage:
        return dict(state_usage)
    if injected_snapshot is not None:
        return dict(injected_snapshot() or _default_usage_snapshot())
    return _default_usage_snapshot()


def create_debate_evaluator_node(
    *,
    config: DebateTerminationConfig | None = None,
    usage_snapshot: Callable[[], Mapping[str, Any]] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Build the Debate Evaluator LangGraph node with injectable dependencies.

    Args:
        config: The validated ``debate_termination`` config. When ``None`` it is
            resolved from the graph's root config (via
            ``resolve_debate_termination_config``) so a real run uses the
            configured group; tests pass an explicit config for determinism.
        usage_snapshot: A callable returning the current usage dict
            ``{calls, tokens, seconds, estimated}``. Tests inject a fixed value.
    """
    resolved_config = config
    resolved_usage = usage_snapshot or _default_usage_snapshot

    def debate_evaluator_node(state: Mapping[str, Any]) -> dict[str, Any]:
        # Resolve the config from the root ``debate_termination`` block when not
        # injected explicitly.
        effective_config = resolved_config
        if effective_config is None:
            root_config = {
                "debate_termination": state.get("debate_termination_config"),
                "max_debate_rounds": state.get("max_debate_rounds"),
            }
            effective_config = resolve_debate_termination_config(root_config)

        debate = state.get("investment_debate_state") or {}
        turns = _turns_from_state(state)
        conflicts = _conflicts_from_state(state)
        # Budget accounting is real, deterministic run-level usage accrued by the
        # Bull/Bear researchers on the state. Prefer it; only fall back to the
        # injected snapshot (used by unit tests) when no usage was recorded.
        usage = _resolve_usage(state, resolved_usage)

        # Disabled mode -> legacy fixed-round routing (single authoritative
        # evaluator still owns the decision; it just reproduces the old rules).
        if not effective_config.enabled:
            decision = _disabled_round_decision(debate, effective_config)
            return _write_decision(state, decision, usage, with_metrics=False)

        # The evaluator is only entitled to judge a *complete* Bull->Bear pair.
        # Validate the exact ordering (Bull, Bear, Bull, Bear, ...) and an even
        # turn count; any malformed/incomplete/out-of-order sequence fails
        # closed to a safe summary route with an explicit stop reason instead of
        # extending the debate.
        if not _valid_paired_turns(turns):
            fallback = RoutingDecision(
                route=DebateRoute.SUMMARIZE,
                stop_reason=StopReason.MALFORMED_STATE,
                next_speaker="",
            )
            return _write_decision(state, fallback, usage, with_metrics=False)

        round_index = len(turns) // 2

        # The current round is the last two turns (Bull then Bear).
        round_turns = turns[-2:] if len(turns) >= 2 else turns
        bull_turn = _last_of_speaker(turns, "Bull")
        bear_turn = turns[-1]

        # Previously cited = union of cited IDs across turns before this round.
        prior_cited: set[str] = set()
        for turn in turns[:-2]:
            prior_cited.update(turn.cited_evidence_ids)
        previously_cited = prior_cited

        bull_stance = _stance_of(bull_turn)
        bear_stance = _stance_of(bear_turn)
        bull_confidence = _confidence_of(bull_turn)
        bear_confidence = _confidence_of(bear_turn)

        # Prior round references per side, for material-change checks. Round 1
        # (round_index == 1) has no prior round, so both references are empty and
        # material change stays False; rounds 2+ compare each side to its own
        # prior same-speaker turn (Bull->Bull, Bear->Bear).
        prior_bull = _prior_speaker_reference(turns[:-2], "Bull") if len(turns) >= 4 else None
        prior_bear = _prior_speaker_reference(turns[:-2], "Bear") if len(turns) >= 4 else None

        manifest = EvidenceManifest.from_records(
            state.get("data_quality_evidence_records") or _EMPTY_RECORDS
        )
        manifest_index = build_evidence_manifest_index(
            state.get("data_quality_evidence_records") or _EMPTY_RECORDS
        )

        target_date = state.get("trade_date")
        gate_verdict = state.get("data_quality_verdict")
        gate_group_statuses = state.get("data_quality_group_statuses") or _EMPTY_STATUSES

        # Conflicts are never fabricated: only the conflicts the model tracked
        # via structured metadata (or a caller supplied) are considered. An
        # action-only divergence (Bull and Bear recommending different actions)
        # without a tracked interpretive/factual conflict is NOT treated as an
        # open blocking conflict, so it cannot keep the debate alive on its own.
        #
        # Derive the conflict list for this completed round from the round's
        # structured conflict assertions. The tracker creates / observes /
        # resolves / escalates conflicts deterministically and validates every
        # cited evidence ID against the gate manifest and target date (fail
        # closed: invalid or future evidence never creates a conflict). The
        # updated list is what the evaluator judges and is persisted back to the
        # debate state for the Research Manager — this closes the runtime gap.
        tracked_conflicts, resolution_notes = derive_conflicts(
            round_index=round_index,
            turns=round_turns,
            manifest=manifest,
            target_date=target_date,
            tracked=conflicts,
        )

        metrics, decision = evaluate_round(
            round_index=round_index,
            round_turns=round_turns,
            previously_cited=previously_cited,
            manifest=manifest,
            target_date=target_date,
            conflicts=tracked_conflicts,
            bull_stance=bull_stance,
            bear_stance=bear_stance,
            bull_confidence=bull_confidence,
            bear_confidence=bear_confidence,
            config=effective_config,
            usage=usage,
            gate_verdict=gate_verdict,
            gate_group_statuses=gate_group_statuses,
            manifest_index=manifest_index,
            prior_no_new_evidence_streak=int(debate.get("no_new_evidence_streak") or 0),
            prior_bull=prior_bull,
            prior_bear=prior_bear,
            bull_evidence_ids=list(bull_turn.cited_evidence_ids or []),
            bull_reasons=list(bull_turn.new_claims or []),
            bear_evidence_ids=list(bear_turn.cited_evidence_ids or []),
            bear_reasons=list(bear_turn.new_claims or []),
        )
        return _write_decision(
            state,
            decision,
            usage,
            with_metrics=True,
            metrics=metrics,
            bull_stance=bull_stance,
            bull_confidence=bull_confidence,
            bear_stance=bear_stance,
            bear_confidence=bear_confidence,
            conflicts=tracked_conflicts,
            resolution_notes=resolution_notes,
        )

    return debate_evaluator_node


def _valid_paired_turns(turns: Sequence[Any]) -> bool:
    """True iff ``turns`` is a complete Bull->Bear sequence with an even count.

    The authoritative ordering is Bull, Bear, Bull, Bear, ... A missing turn,
    an odd count, or an out-of-order speaker (e.g. Bear then Bull, or a Bull
    adjudged in the middle) returns ``False`` so the evaluator fails closed.
    """
    if not turns:
        return False
    if len(turns) % 2 != 0:
        return False
    for index, turn in enumerate(turns):
        expected = "Bull" if index % 2 == 0 else "Bear"
        if turn.speaker != expected:
            return False
    return True


def _last_of_speaker(turns: Sequence[Any], speaker: str) -> Any:
    for turn in reversed(turns):
        if turn.speaker == speaker:
            return turn
    return None


def _stance_of(turn: Any) -> Stance:
    if turn is None:
        return Stance.HOLD
    stance = getattr(turn, "stance", None)
    if stance is None:
        return Stance.HOLD
    if isinstance(stance, Stance):
        return stance
    # A string value ("Hold") or a failed turn whose enum was stringified
    # during serialization ("Stance.HOLD"); normalize both deterministically.
    return _coerce_stance(stance)


def _coerce_stance(value: Any) -> Stance:
    """Coerce a stance value (enum/string) to a :class:`Stance`; fall back Hold."""
    if isinstance(value, Stance):
        return value
    text = str(value)
    # ``Stance.HOLD`` -> ``HOLD``
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    text = text.strip().lower()
    mapping = {
        "sell": Stance.SELL,
        "underweight": Stance.UNDERWEIGHT,
        "hold": Stance.HOLD,
        "overweight": Stance.OVERWEIGHT,
        "buy": Stance.BUY,
        "stance.sell": Stance.SELL,
        "stance.underweight": Stance.UNDERWEIGHT,
        "stance.hold": Stance.HOLD,
        "stance.overweight": Stance.OVERWEIGHT,
        "stance.buy": Stance.BUY,
    }
    return mapping.get(text, Stance.HOLD)


def _confidence_of(turn: Any) -> float:
    if turn is None:
        return 0.0
    return float(getattr(turn, "confidence", 0.0) or 0.0)


def _prior_speaker_reference(turns: Sequence[Any], speaker: str) -> _SideReference | None:
    """The most recent *complete* turn for ``speaker`` in ``turns``.

    ``turns`` is the sequence of completed turns *before* the current round
    (``turns[:-2]``). Only a fully completed same-speaker turn is a valid
    change baseline: a partial / malformed sequence (e.g. an unpaired Bull
    whose Bear has not spoken) is not a rounded reference and should never be
    compared, so this returns ``None`` unless a complete prior round exists.
    """
    target = _last_of_speaker(turns, speaker)
    if target is None:
        return None
    return _SideReference(
        stance=_stance_of(target),
        confidence=_confidence_of(target),
        evidence_ids=list(target.cited_evidence_ids or []),
        reasons=list(target.new_claims or []),
    )


def _write_decision(
    state: Mapping[str, Any],
    decision: RoutingDecision,
    usage: Mapping[str, Any],
    *,
    with_metrics: bool,
    metrics: RoundMetrics | None = None,
    bull_stance: Stance | None = None,
    bull_confidence: float = 0.0,
    bear_stance: Stance | None = None,
    bear_confidence: float = 0.0,
    conflicts: Sequence[ConflictRecord] | None = None,
    resolution_notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    debate = dict(state.get("investment_debate_state") or {})

    round_metrics = list(debate.get("round_metrics") or [])
    if with_metrics and metrics is not None:
        round_metrics.append(metrics.to_dict())
    debate["round_metrics"] = round_metrics

    if with_metrics:
        stances = dict(debate.get("stances") or {})
        if bull_stance is not None:
            stances["Bull"] = StanceSnapshot(
                stance=bull_stance,
                confidence=bull_confidence,
            ).to_dict()
        if bear_stance is not None:
            stances["Bear"] = StanceSnapshot(
                stance=bear_stance,
                confidence=bear_confidence,
            ).to_dict()
        debate["stances"] = stances

        if metrics is not None:
            debate["no_new_evidence_streak"] = (
                0 if metrics.new_valid_evidence_count else int(
                    debate.get("no_new_evidence_streak") or 0
                ) + 1
            )

    debate["budget"] = {
        "calls": int(usage.get("calls", 0)),
        "tokens": int(usage.get("tokens", 0)),
        "seconds": float(usage.get("seconds", 0.0)),
        "estimated": bool(usage.get("estimated", False)),
    }

    # Persist the tracked conflict list (serialized) and a safe structured summary
    # so the downstream Research Manager and any report read the *tracked*
    # conflicts — not a fabricated view. When no conflicts were derived, an empty
    # list and an empty summary are written (missing metadata -> no conflict).
    if conflicts is not None:
        debate["conflicts"] = [c.to_dict() for c in conflicts]
        debate["conflict_summary"] = build_conflict_summary(
            conflicts, resolution_notes
        ).to_dict()

    return {
        "investment_debate_state": debate,
        "debate_termination_decision": decision.to_dict(),
    }


def _disabled_round_decision(
    debate: Mapping[str, Any],
    config: DebateTerminationConfig,
) -> RoutingDecision:
    """Legacy fixed-round routing for the disabled baseline mode.

    Reproduces ``should_continue_debate``: when ``count >= 2 * max_debate_rounds``
    the debate ends (summarize with ``max_rounds_reached``); otherwise it
    continues to the next complete round opener (Bull). Because the graph runs a
    full Bull->Bear pair before the evaluator, a continuing round always opens
    with the Bull — exactly the legacy count-threshold result with the correct
    opener, so disabled mode preserves the legacy route and the legacy default
    round count.
    """
    from tradingagents.debate.models import DecisionTraceEntry

    count = int(debate.get("count") or 0)
    reached = count >= 2 * config.max_debate_rounds
    if reached:
        return RoutingDecision(
            route=DebateRoute.SUMMARIZE,
            stop_reason=StopReason.MAX_ROUNDS_REACHED,
            next_speaker="",
            trace=[
                DecisionTraceEntry(
                    rule=RULE_DISABLED_FIXED,
                    activated=True,
                    thresholds={"max_debate_rounds": config.max_debate_rounds},
                    actual={"count": count},
                )
            ],
        )
    return RoutingDecision(
        route=DebateRoute.CONTINUE,
        stop_reason=StopReason.CONTINUE_FOR_NEW_EVIDENCE,
        next_speaker="Bull",
        trace=[
            DecisionTraceEntry(
                rule=RULE_DISABLED_FIXED,
                activated=False,
                thresholds={"max_debate_rounds": config.max_debate_rounds},
                actual={"count": count, "next_speaker": "Bull"},
            )
        ],
    )


RULE_DISABLED_FIXED = "legacy_fixed_rounds"
