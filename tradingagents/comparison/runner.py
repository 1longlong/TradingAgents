"""Phase 4A runner: deterministic offline replay + fail-closed aggregation.

This module is the **pure deterministic offline comparison model/runner**. It
never invokes an LLM, a data vendor, or the network. It consumes *scripted*
(already-recorded) evidence snapshots and Bull/Bear turn sequences and replays
both strategies — the legacy fixed-round baseline and the dynamic policy — over
**identical** case identity and evidence snapshot, so any difference is
attributable to the policy, not the input.

Two capabilities:

1. :func:`replay_scripted_case` — run a scripted case through both strategies
   using the pure :func:`~tradingagents.debate.evaluator.evaluate_round` rules.
   The fixed baseline always completes ``max_debate_rounds``; the dynamic policy
   may stop early. Both see the exact same rounds, snapshot, and policy version.

2. :func:`pair_and_aggregate` — take already-recorded per-strategy
   :class:`CaseResult` objects, pair them by identity (fail closed on any
   mismatch via :class:`PairingError`), and derive a :class:`ComparisonReport`.

All timing/token inputs are recorded (measured or estimated); no wall clock is
read here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from tradingagents.comparison.metric_formulas import ratio
from tradingagents.comparison.schemas import (
    INPUT_EXHAUSTED_STOP_REASON,
    CaseAggregate,
    CaseIdentity,
    CaseResult,
    ComparisonReport,
    PairingError,
    StrategyKey,
    TraceabilityStatus,
)
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.evidence_manifest import EvidenceManifest
from tradingagents.debate.models import ConflictRecord, DebateRoute, DebateTurn, StopReason

# Strategy keys, fixed order for reporting.
_STRATEGY_ORDER = (StrategyKey.FIXED, StrategyKey.DYNAMIC)


@dataclass(frozen=True)
class ScriptedRound:
    """One scripted Bull + Bear round, identical for both strategies.

    ``bull`` and ``bear`` are the typed turns; ``calls``/``tokens``/
    ``seconds``/``estimated`` are the recorded usage for completing this round
    (they are inputs, replayed verbatim, never re-estimated here). ``conflicts``
    are the pre-derived open conflicts for this round (or empty).
    """

    index: int
    bull: DebateTurn
    bear: DebateTurn
    calls: int = 2
    tokens: int = 0
    seconds: float = 0.0
    estimated: bool = True
    conflicts: list[ConflictRecord] = field(default_factory=list)
    gate_verdict: str = ""
    gate_group_statuses: list[dict[str, Any]] | None = None
    quality_status: str = ""


@dataclass(frozen=True)
class ScriptedCase:
    """A complete scripted case: identical evidence snapshot + debate inputs.

    ``evidence_records`` are the serialized gate-evidence records (the manifest
    from which valid-new-evidence is judged). ``rounds`` are the scripted
    time-ordered Bull/Bear pairs, all consumed identically by both strategies.
    ``max_debate_rounds`` is the hard cap both strategies honor; the dynamic
    policy's ``config`` carries the versioned termination knobs. ``snapshot_id``
    and ``policy_version`` pin the identity.
    """

    identity: CaseIdentity
    evidence_records: list[dict[str, Any]]
    rounds: list[ScriptedRound]
    config: DebateTerminationConfig
    target_date: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", self.identity)
        object.__setattr__(self, "evidence_records", list(self.evidence_records or []))
        object.__setattr__(self, "rounds", list(self.rounds or []))
        object.__setattr__(self, "config", self.config)
        object.__setattr__(self, "target_date", str(self.target_date))

    @property
    def max_debate_rounds(self) -> int:
        return self.config.max_debate_rounds


def replay_scripted_case(sc: ScriptedCase) -> dict[StrategyKey, CaseResult]:
    """Replay ``sc`` through both strategies and return matched results.

    Returns a ``{strategy: CaseResult}`` dict. Both entries carry the identical
    ``sc.identity`` (guaranteed by construction). This is fully deterministic and
    LLM-free; the dynamic policy calls only the pure evaluator rules.
    """
    fixed = _replay_fixed(sc)
    dynamic = _replay_dynamic(sc)
    return {StrategyKey.FIXED: fixed, StrategyKey.DYNAMIC: dynamic}


def _replay_fixed(sc: ScriptedCase) -> CaseResult:
    """Fixed-round baseline: always completes exactly ``max_debate_rounds``.

    It never early-stops. It consumes the first ``max_debate_rounds`` scripted
    rounds and sums their recorded usage. If the scripted input has fewer rounds
    than the cap, it runs only the rounds present (the cap is honored, not
    exceeded).
    """
    completed = sc.rounds[: sc.max_debate_rounds]
    calls = sum(r.calls for r in completed)
    tokens = sum(r.tokens for r in completed)
    seconds = sum(r.seconds for r in completed)
    estimated = any(r.estimated for r in completed) if completed else False
    cited = _valid_cited_ids(sc, completed)
    # Fixed baseline: a strong conclusion is recorded only if the eligible
    # evidence supports it (mirrors gate verdict). The fixed strategy never
    # early-stops; its stop reason is the max-rounds cap if it completed the
    # cap, input exhaustion if the scripted input was shorter, else "".
    if not completed:
        fixed_stop_reason = ""
    elif len(completed) >= sc.max_debate_rounds:
        fixed_stop_reason = StopReason.MAX_ROUNDS_REACHED.value
    else:
        fixed_stop_reason = INPUT_EXHAUSTED_STOP_REASON
    return CaseResult(
        strategy=StrategyKey.FIXED,
        identity=sc.identity,
        llm_calls=calls,
        tool_calls=0,
        input_tokens=tokens,
        output_tokens=0,
        total_tokens=tokens,
        elapsed_seconds=seconds,
        debate_rounds=len(completed),
        early_stopped=False,
        stop_reason=fixed_stop_reason,
        valid_cited_evidence_ids=cited,
        total_eligible_evidence_ids=_eligible_count(sc),
        strong_conclusion=_fixed_strong_conclusion(sc),
        gate_verdict=_final_gate_verdict(sc),
        quality_status=_final_quality(sc),
        estimated=estimated,
        traceability_status=TraceabilityStatus.PENDING,
        traceability_scores=[],
    )


def _replay_dynamic(sc: ScriptedCase) -> CaseResult:
    """Dynamic policy: replay the evaluator after each scripted round.

    The evaluator stops early per the rule ordering (no-new-evidence, consensus,
    budget exhaustion, max rounds, etc.). The dynamic result consumes exactly
    the rounds the evaluator allowed and records their summed usage.

    ``early_stopped`` is ``True`` ONLY when the evaluator made a genuine
    termination decision (a non-``continue`` route whose stop reason is not the
    fixed ``max_rounds_reached`` cap) before the hard round cap. A run that
    simply exhausts its available scripted rounds (fewer scripted rounds than
    the policy wanted to consume, with no termination decision) is **not** an
    early stop: it is recorded as ``stop_reason == INPUT_EXHAUSTED_STOP_REASON``
    and ``early_stopped == False``. ``stop_reason`` preserves the *actual*
    deterministic reason the evaluator produced so the termination decision is
    auditable, never a generic/inferred label. A budget exhaustion (rule 2)
    means the dynamic policy must never exceed the hard cap or the summary
    reserve — verified in the fixtures.
    """
    from tradingagents.debate.evaluator import evaluate_round

    manifest = EvidenceManifest.from_records(sc.evidence_records)
    previously_cited: set[str] = set()
    executed: list[ScriptedRound] = []
    no_new_streak = 0
    prior_bull = None
    prior_bear = None
    usage: dict[str, Any] = {"calls": 0, "tokens": 0, "seconds": 0.0, "estimated": False}
    # ``termination`` is the last non-CONTINUE decision (or None if the scripted
    # input ran out before the policy made any termination decision).
    termination = None

    for round_def in sc.rounds:
        if len(executed) >= sc.max_debate_rounds:
            break
        round_turns = [round_def.bull, round_def.bear]
        usage = {
            "calls": usage["calls"] + round_def.calls,
            "tokens": usage["tokens"] + round_def.tokens,
            "seconds": usage["seconds"] + round_def.seconds,
            "estimated": usage["estimated"] or round_def.estimated,
        }
        round_index = len(executed) + 1
        metrics, decision = evaluate_round(
            round_index=round_index,
            round_turns=round_turns,
            previously_cited=previously_cited,
            manifest=manifest,
            target_date=sc.target_date,
            conflicts=round_def.conflicts,
            bull_stance=round_def.bull.stance,
            bear_stance=round_def.bear.stance,
            bull_confidence=round_def.bull.confidence,
            bear_confidence=round_def.bear.confidence,
            config=sc.config,
            usage=usage,
            gate_verdict=round_def.gate_verdict or _final_gate_verdict(sc),
            gate_group_statuses=round_def.gate_group_statuses,
            prior_no_new_evidence_streak=no_new_streak,
            prior_bull=prior_bull,
            prior_bear=prior_bear,
            bull_evidence_ids=list(round_def.bull.cited_evidence_ids),
            bull_reasons=list(round_def.bull.new_claims),
            bear_evidence_ids=list(round_def.bear.cited_evidence_ids),
            bear_reasons=list(round_def.bear.new_claims),
        )
        executed.append(round_def)
        previously_cited.update(round_def.bull.cited_evidence_ids)
        previously_cited.update(round_def.bear.cited_evidence_ids)
        no_new_streak = 0 if metrics.new_valid_evidence_count else no_new_streak + 1
        prior_bull = _to_side_ref(round_def.bull)
        prior_bear = _to_side_ref(round_def.bear)
        if decision.route != DebateRoute.CONTINUE:
            termination = decision
            break

    # Distinguish a genuine dynamic termination decision from input exhaustion:
    # if the policy made no non-CONTINUE decision, the scripted rounds simply
    # ran out -> input exhaustion, never an early stop.
    if termination is not None:
        stop_reason = termination.stop_reason.value
        if not executed:
            early_stopped = False
        else:
            early_stopped = (
                stop_reason != StopReason.MAX_ROUNDS_REACHED.value
                and len(executed) < sc.max_debate_rounds
            )
    else:
        stop_reason = "" if not executed else INPUT_EXHAUSTED_STOP_REASON
        early_stopped = False

    calls = usage["calls"]
    tokens = usage["tokens"]
    seconds = usage["seconds"]
    return CaseResult(
        strategy=StrategyKey.DYNAMIC,
        identity=sc.identity,
        llm_calls=calls,
        tool_calls=0,
        input_tokens=tokens,
        output_tokens=0,
        total_tokens=tokens,
        elapsed_seconds=seconds,
        debate_rounds=len(executed),
        early_stopped=early_stopped,
        stop_reason=stop_reason,
        valid_cited_evidence_ids=_valid_cited_ids(sc, executed),
        total_eligible_evidence_ids=_eligible_count(sc),
        strong_conclusion=_fixed_strong_conclusion(sc),
        gate_verdict=_final_gate_verdict(sc),
        quality_status=_final_quality(sc),
        estimated=usage["estimated"],
        traceability_status=TraceabilityStatus.PENDING,
        traceability_scores=[],
    )


def _valid_cited_ids(sc: ScriptedCase, rounds: Sequence[ScriptedRound]) -> list[str]:
    """Union of **valid** NEW cited evidence IDs across the executed rounds.

    Validity follows the authoritative valid-new-evidence rules (INV-2): an ID
    counts only when it is known to the manifest, High/Medium, observed on or
    before the target date, and explicitly linked to a claim. This is the only
    source for the evidence-citation-coverage numerator — never raw prose or a
    bare citation count.
    """
    from tradingagents.debate.evidence_manifest import (
        EvidenceManifest,
        is_valid_new_evidence,
    )

    manifest = EvidenceManifest.from_records(sc.evidence_records)
    gathered: list[str] = []
    previously_cited: set[str] = set()
    for round_def in rounds:
        for turn in (round_def.bull, round_def.bear):
            linked = set(turn.linked_evidence_ids())
            for eid in getattr(turn, "cited_evidence_ids", []):
                if is_valid_new_evidence(
                    evidence_id=eid,
                    previously_cited=previously_cited,
                    currently_linked=eid in linked,
                    manifest=manifest,
                    target_date=sc.target_date,
                ) and eid not in gathered:
                    gathered.append(eid)
        previously_cited.update(round_def.bull.cited_evidence_ids)
        previously_cited.update(round_def.bear.cited_evidence_ids)
    return gathered


def _eligible_count(sc: ScriptedCase) -> int:
    from tradingagents.debate.evidence_manifest import EvidenceManifest

    manifest = EvidenceManifest.from_records(sc.evidence_records)
    return len(manifest.valid_ids)


def _fixed_strong_conclusion(sc: ScriptedCase) -> bool:
    verdict = (_final_gate_verdict(sc) or "").lower()
    return verdict != "blocked"


def _final_gate_verdict(sc: ScriptedCase) -> str:
    for round_def in reversed(sc.rounds):
        if round_def.gate_verdict:
            return round_def.gate_verdict
    return ""


def _final_quality(sc: ScriptedCase) -> str:
    for round_def in reversed(sc.rounds):
        if round_def.quality_status:
            return round_def.quality_status
    return ""


def _to_side_ref(turn: DebateTurn):
    from tradingagents.debate.evaluator import _SideReference

    return _SideReference(
        stance=turn.stance,
        confidence=turn.confidence,
        evidence_ids=list(turn.cited_evidence_ids),
        reasons=list(turn.new_claims),
    )


def pair_and_aggregate(results: Sequence[CaseResult]) -> ComparisonReport:
    """Pair FIXED and DYNAMIC results by identity and aggregate.

    Fail closed: any result that has no matching partner with the exact same
    identity, any duplicated strategy/identity pair, or any identity string
    mismatch raises :class:`PairingError`. Returns a :class:`ComparisonReport`
    with deterministic derived sums/rates.

    Identity must be **exact and equal** across both strategies. If either
    strategy has an entry for an identity the other lacks, comparison cannot be
    done on an equal footing and the whole run is rejected.
    """
    fixed: dict[str, CaseResult] = {}
    dynamic: dict[str, CaseResult] = {}

    for result in results:
        key = result.identity.to_dict()
        from json import dumps

        identity_key = dumps(key, sort_keys=True)
        bucket = fixed if result.strategy == StrategyKey.FIXED else dynamic
        if identity_key in bucket:
            raise PairingError(
                f"duplicate {result.strategy.value} result for identity {identity_key}"
            )
        bucket[identity_key] = result

    fixed_keys = set(fixed)
    dynamic_keys = set(dynamic)
    if fixed_keys != dynamic_keys:
        missing = (fixed_keys - dynamic_keys) or (dynamic_keys - fixed_keys)
        raise PairingError(
            "case identity mismatch between strategies: " + ", ".join(sorted(missing))
        )

    paired: list[tuple[CaseIdentity, CaseAggregate, CaseAggregate]] = []
    for identity_key in sorted(fixed_keys):
        f = _reconstruct_identity(fixed[identity_key])
        d = _reconstruct_identity(dynamic[identity_key])
        if not f.identity.matches(d.identity):
            raise PairingError(
                f"identity mismatch: fixed={f.identity.to_dict()} dynamic={d.identity.to_dict()}"
            )
        paired.append((f.identity, f.as_aggregate(), d.as_aggregate()))

    f_total_calls = sum(a.llm_calls for _, a, _ in paired)
    d_total_calls = sum(a.llm_calls for _, _, a in paired)
    f_total_tool_calls = sum(a.tool_calls for _, a, _ in paired)
    d_total_tool_calls = sum(a.tool_calls for _, _, a in paired)
    f_total_tokens = sum(a.total_tokens for _, a, _ in paired)
    d_total_tokens = sum(a.total_tokens for _, _, a in paired)
    f_total_time = sum(a.elapsed_seconds for _, a, _ in paired)
    d_total_time = sum(a.elapsed_seconds for _, _, a in paired)
    f_total_rounds = sum(a.debate_rounds for _, a, _ in paired)
    d_total_rounds = sum(a.debate_rounds for _, _, a in paired)
    f_early = sum(1 for _, a, _ in paired if a.early_stop_rate == 1.0)
    d_early = sum(1 for _, _, a in paired if a.early_stop_rate == 1.0)
    d_early_rate = ratio(d_early, len(paired)) if paired else None
    f_false = sum(a.false_strong_conclusion_count for _, a, _ in paired)
    d_false = sum(a.false_strong_conclusion_count for _, _, a in paired)
    f_strong = sum(a.strong_conclusion_count for _, a, _ in paired)
    d_strong = sum(a.strong_conclusion_count for _, _, a in paired)
    f_false_rate = ratio(f_false, f_strong)
    d_false_rate = ratio(d_false, d_strong)
    # Honest usage-provenance status: count estimated cases per strategy so an
    # estimated run is never presented as a fully-measured aggregate.
    f_estimated = sum(1 for _, a, _ in paired if a.tool_usage_estimated)
    d_estimated = sum(1 for _, _, a in paired if a.tool_usage_estimated)
    # Preserve the actual stop reason per strategy (counts), never re-label a
    # termination decision; an empty reason ("" no rounds) is dropped.
    f_stop_reasons = _count_stop_reasons(a.stop_reason for _, a, _ in paired)
    d_stop_reasons = _count_stop_reasons(a.stop_reason for _, _, a in paired)

    return ComparisonReport(
        total_cases=len(paired),
        paired_cases=paired,
        fixed_total_llm_calls=f_total_calls,
        dynamic_total_llm_calls=d_total_calls,
        fixed_total_tool_calls=f_total_tool_calls,
        dynamic_total_tool_calls=d_total_tool_calls,
        fixed_total_tokens=f_total_tokens,
        dynamic_total_tokens=d_total_tokens,
        fixed_total_time=f_total_time,
        dynamic_total_time=d_total_time,
        fixed_total_rounds=f_total_rounds,
        dynamic_total_rounds=d_total_rounds,
        fixed_early_stop_count=f_early,
        dynamic_early_stop_count=d_early,
        dynamic_early_stop_rate=d_early_rate,
        fixed_false_strong_count=f_false,
        dynamic_false_strong_count=d_false,
        fixed_false_strong_rate=f_false_rate,
        dynamic_false_strong_rate=d_false_rate,
        fixed_estimated_cases=f_estimated,
        dynamic_estimated_cases=d_estimated,
        fixed_stop_reasons=f_stop_reasons,
        dynamic_stop_reasons=d_stop_reasons,
    )


def _count_stop_reasons(reasons: Sequence[str]) -> dict[str, int]:
    """Count occurrences of each non-empty stop reason (stable, sorted keys)."""
    counts: dict[str, int] = {}
    for reason in reasons:
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _reconstruct_identity(result: CaseResult) -> CaseResult:
    return result
