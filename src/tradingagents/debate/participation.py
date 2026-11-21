"""Deterministic, pure participation truth for the Bull/Bear debate.

The Research Manager needs to know which speakers actually executed so it never
attributes claims to a speaker that produced no response. This module derives
that truth from structured debate state only — it is pure, LLM-free and
deterministic, and it never invents a participant.

Evidence rules (fail closed toward ``unverified``):

- **Structured execution evidence** is the authoritative signal: a serialized
  debater turn in ``turns`` with ``speaker == "Bull"/"Bear"``. When
  ``turns`` is present it is trusted.
- **Legacy prose alone does NOT prove execution.** A non-empty
  ``bull_history``/``bear_history`` in a *legacy* state (no structured ``turns``
  list, or one that conflicts with the prose) is reported as ``legacy`` /
  ``unverified`` rather than promoted to ``executed``. This prevents treating a
  printed history string as proof that a model call actually ran.
- The skip/stop reason and skipped speakers come from
  ``debate_termination_decision`` (``route``/``stop_reason``/trace), never from
  guessed values.

The result is a JSON-safe dict consumed by the Research Manager template, the
report artifacts and the tests:

    {
      "bull": "executed" | "not_executed" | "unverified",
      "bear": "executed" | "not_executed" | "unverified",
      "bull_turns": int,
      "bear_turns": int,
      "status": "both" | "one" | "none" | "unknown",
      "executed_speakers": [str, ...],
      "missing_speakers": [str, ...],
      "skipped_speakers": [str, ...],
      "stop_reason": str,
      "skip_reason": str | None,
      "evidence": "structured" | "legacy" | "conflicting" | "absent",
      "complete": bool,
    }

``status`` is derived from the authoritative per-speaker states:

- ``both`` — both executed,
- ``one`` — exactly one executed and the other is known not to have,
- ``none`` — neither executed,
- ``unknown`` — any speaker is ``unverified`` (legacy/absent/conflicting).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SPEAKERS = ("Bull", "Bear")

STATE_EXECUTED = "executed"
STATE_NOT_EXECUTED = "not_executed"
STATE_UNVERIFIED = "unverified"

EVIDENCE_STRUCTURED = "structured"
EVIDENCE_LEGACY = "legacy"
EVIDENCE_CONFLICTING = "conflicting"
EVIDENCE_ABSENT = "absent"

STATUS_BOTH = "both"
STATUS_ONE = "one"
STATUS_NONE = "none"
STATUS_UNKNOWN = "unknown"


def _count_turn_speakers(turns: Any) -> dict[str, int]:
    """Count well-formed structured turns per speaker.

    Only a mapping turn whose ``speaker`` is exactly ``"Bull"``/``"Bear"``
    counts. A non-dict turn, or a turn with a missing/unknown speaker, is NOT
    trusted as execution evidence (it is ignored for counting; the caller treats
    a structured state with no valid turns as unverified below).
    """
    counts = dict.fromkeys(_SPEAKERS, 0)
    if not isinstance(turns, list):
        return counts
    for turn in turns:
        if not isinstance(turn, Mapping):
            continue
        speaker = turn.get("speaker")
        # Guard against unhashable speakers (e.g. a list) before dict membership;
        # only an exact str "Bull"/"Bear" is a valid count.
        if isinstance(speaker, str) and speaker in counts:
            counts[speaker] += 1
    return counts


def _valid_speaker(value: Any) -> bool:
    """True only for the exact strings ``"Bull"``/``"Bear"`` (hashable guard)."""
    return isinstance(value, str) and value in _SPEAKERS


def _malformed_structured(turns: Any) -> bool:
    """True when a structured ``turns`` list exists but cannot be trusted.

    A ``turns`` list containing any non-mapping entry, or any entry whose
    ``speaker`` is not exactly ``"Bull"``/``"Bear"``, is malformed/conflicting:
    the structured evidence cannot be trusted, so speakers stay unverified
    rather than being inferred from ambiguous data.
    """
    if not isinstance(turns, list):
        return False
    for turn in turns:
        if not isinstance(turn, Mapping):
            return True
        if not _valid_speaker(turn.get("speaker")):
            return True
    return False


def _history_nonempty(investment_debate_state: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "Bull": bool(str(investment_debate_state.get("bull_history", "") or "").strip()),
        "Bear": bool(str(investment_debate_state.get("bear_history", "") or "").strip()),
    }


def _has_structured_turns(investment_debate_state: Mapping[str, Any]) -> bool:
    turns = investment_debate_state.get("turns")
    return isinstance(turns, list) and len(turns) > 0


def _speaker_states(
    counts: dict[str, int],
    history_nonempty: dict[str, bool],
    has_structured: bool,
    malformed: bool = False,
) -> tuple[dict[str, str], str]:
    """Derive per-speaker state and the evidence category, failing closed."""
    states: dict[str, str] = {}
    if has_structured and malformed:
        # A structured turns list that cannot be trusted: do not infer any
        # speaker as executed. Report unverified (conflicting structured data);
        # prose is not promoted to evidence either.
        for speaker in _SPEAKERS:
            if counts[speaker] > 0 or history_nonempty[speaker]:
                states[speaker] = STATE_UNVERIFIED
            else:
                states[speaker] = STATE_UNVERIFIED
        return states, EVIDENCE_CONFLICTING
    if has_structured:
        # Structured turns are authoritative for *positive* execution. A
        # structured state whose prose is non-empty for a speaker with no
        # structured turn is a conflict; report it, never promote it.
        conflict = False
        for speaker in _SPEAKERS:
            if counts[speaker] > 0:
                states[speaker] = STATE_EXECUTED
            elif history_nonempty[speaker]:
                states[speaker] = STATE_UNVERIFIED
                conflict = True
            else:
                states[speaker] = STATE_NOT_EXECUTED
        return states, EVIDENCE_CONFLICTING if conflict else EVIDENCE_STRUCTURED

    # Legacy: no structured turns at all. History alone cannot prove a call.
    if not any(history_nonempty.values()):
        return dict.fromkeys(_SPEAKERS, STATE_NOT_EXECUTED), EVIDENCE_ABSENT

    states = {
        speaker: (STATE_UNVERIFIED if history_nonempty[speaker] else STATE_NOT_EXECUTED)
        for speaker in _SPEAKERS
    }
    return states, EVIDENCE_LEGACY


def _status(states: Mapping[str, str]) -> str:
    executed = [s for s in _SPEAKERS if states[s] == STATE_EXECUTED]
    unverified = [s for s in _SPEAKERS if states[s] == STATE_UNVERIFIED]
    if unverified:
        return STATUS_UNKNOWN
    if len(executed) == 2:
        return STATUS_BOTH
    if len(executed) == 1:
        return STATUS_ONE
    return STATUS_NONE


def _skipped_speakers(states: Mapping[str, str], stop_reason: str) -> list[str]:
    """Speakers known not to have executed when the debate stopped early."""
    if not stop_reason:
        return []
    return [s for s in _SPEAKERS if states[s] == STATE_NOT_EXECUTED]


def _decision_from(investment_debate_state: Mapping[str, Any], decision: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Resolve the authoritative termination decision.

    The real stop/refusal lives at TOP-LEVEL ``state.debate_termination_decision``
    (not only inside ``investment_debate_state``). The explicitly supplied
    ``decision`` wins; otherwise the embedded copy is used; otherwise empty.
    """
    if isinstance(decision, Mapping):
        return decision
    embedded = investment_debate_state.get("debate_termination_decision")
    return embedded if isinstance(embedded, Mapping) else {}


def _refused_speaker(decision: Mapping[str, Any]) -> str:
    """Extract the refused speaker from a termination decision.

    ``refused_speaker`` may be top-level or nested under the trace entry's
    ``actual`` (the pre-call guard records it there). Either location is
    honoured; an absent value is ``""``.
    """
    refused = str(decision.get("refused_speaker", "") or "")
    if refused:
        return refused
    trace = decision.get("trace")
    if isinstance(trace, list):
        for entry in trace:
            if not isinstance(entry, Mapping):
                continue
            actual = entry.get("actual")
            if isinstance(actual, Mapping):
                candidate = str(actual.get("refused_speaker", "") or "")
                if candidate:
                    return candidate
    return str(decision.get("next_speaker", "") or "")


def summarize_participation(
    investment_debate_state: Mapping[str, Any] | None,
    *,
    debate_termination_decision: Mapping[str, Any] | None = None,
    gate_verdict: str | None = None,
) -> dict[str, Any]:
    """Summarize who actually executed in the Bull/Bear debate (pure).

    ``investment_debate_state`` may be a legacy or partial mapping; a missing /
    non-mapping state yields an ``unknown``/``absent`` summary rather than a
    fabricated "both executed". The authoritative ``debate_termination_decision``
    is supplied explicitly (it lives at TOP-LEVEL state, not only inside the
    debate state) and is merged with any embedded copy. ``gate_verdict`` lets a
    blocked run with zero turns report an explicit ``data_quality_blocked`` skip
    rather than ``unknown``.
    """
    state = investment_debate_state if isinstance(investment_debate_state, Mapping) else {}
    decision = _decision_from(state, debate_termination_decision)
    stop_reason = str(decision.get("stop_reason", "") or "")
    blocked = str(gate_verdict or "") == "blocked"

    has_structured = _has_structured_turns(state)
    counts = _count_turn_speakers(state.get("turns"))
    history_nonempty = _history_nonempty(state)
    malformed = _malformed_structured(state.get("turns"))
    states, evidence = _speaker_states(counts, history_nonempty, has_structured, malformed)

    # A pre-call refusal recorded in the termination decision is authoritative
    # that the refused speaker did not execute, even if there is no turn.
    refused = _refused_speaker(decision)
    for speaker in _SPEAKERS:
        if refused == speaker and states[speaker] != STATE_EXECUTED:
            states[speaker] = STATE_NOT_EXECUTED

    status = _status(states)
    executed = [s for s in _SPEAKERS if states[s] == STATE_EXECUTED]
    missing = [s for s in _SPEAKERS if states[s] == STATE_NOT_EXECUTED]
    skipped = _skipped_speakers(states, stop_reason)
    skip_reason = stop_reason or None
    if refused and stop_reason:
        skip_reason = f"{stop_reason}:{refused.lower()}"

    # A blocked run with no executed speaker has an explicit, deterministic
    # skip reason (data quality gate), never an ambiguous "unknown".
    if blocked and status == STATUS_NONE and not any(history_nonempty.values()):
        skip_reason = "data_quality_blocked"
        evidence = evidence if evidence != EVIDENCE_ABSENT else EVIDENCE_STRUCTURED
        if not skipped:
            skipped = list(_SPEAKERS)

    return {
        "bull": states["Bull"],
        "bear": states["Bear"],
        "bull_turns": int(counts["Bull"]),
        "bear_turns": int(counts["Bear"]),
        "status": status,
        "executed_speakers": executed,
        "missing_speakers": missing,
        "skipped_speakers": skipped,
        "stop_reason": stop_reason,
        "skip_reason": skip_reason,
        "evidence": evidence,
        "blocked": blocked,
        "complete": status == STATUS_BOTH,
    }


def is_full_two_sided(participation: Mapping[str, Any]) -> bool:
    """True only when both speakers are authoritatively confirmed executed."""
    return participation.get("status") == STATUS_BOTH


def participation_prompt_block(participation: Mapping[str, Any]) -> str:
    """A deterministic, human-readable participation statement for a prompt."""
    status = participation.get("status", STATUS_UNKNOWN)
    if status == STATUS_BOTH:
        return (
            "Debate participation (authoritative): both the Bull and the Bear "
            "produced a response; this is a complete two-sided debate."
        )
    executed = participation.get("executed_speakers") or []
    missing = participation.get("missing_speakers") or []
    skipped = participation.get("skipped_speakers") or []
    evidence = participation.get("evidence")
    reason = participation.get("skip_reason") or participation.get("stop_reason") or "unknown"
    # Whose status is unknown (unverified)/not executed — never claim "no speaker
    # executed" for an unverified speaker.
    unverified = [
        s for s in _SPEAKERS if participation.get(s.lower()) == STATE_UNVERIFIED
    ]
    parts = ["Debate participation (authoritative): this is NOT a complete two-sided debate."]
    if executed:
        parts.append(f"Speakers confirmed executed: {', '.join(executed)}.")
    elif unverified:
        parts.append("No speaker is confirmed executed; execution status is unverified.")
    else:
        parts.append("No speaker executed a model call.")
    if unverified:
        parts.append(
            "Speakers with UNVERIFIED execution (do not attribute claims to them): "
            f"{', '.join(unverified)}."
        )
    if missing:
        parts.append(
            f"Speakers with NO response (do not attribute claims to them): {', '.join(missing)}."
        )
    if skipped:
        parts.append(f"Skipped for stop reason: {', '.join(skipped)} ({reason}).")
    if evidence in (EVIDENCE_LEGACY, EVIDENCE_CONFLICTING, EVIDENCE_ABSENT):
        parts.append(
            f"Execution evidence is {evidence}; unconfirmed participants are treated as unverified, not as having spoken."
        )
    parts.append(
        "Do not invent or attribute any argument, conflict, approval or position to a speaker that did not respond."
    )
    return " ".join(parts)
