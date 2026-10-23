"""Deterministic conflict tracker: create, observe, resolve, escalate.

This is the runtime gap this change closes: the ``ConflictRecord`` model existed
but nothing created or lifecycle-managed it. This module provides the pure,
deterministic tracker that derives conflicts **only** from the structured
``conflict_assertions`` already carried on each :class:`DebateTurn` (parsed by
``turn.py`` from the ``DEBATE_METADATA`` marker). It never reasons over free-form
prose or hidden chain-of-thought, and it never guesses a conflict when the
required structured metadata is absent.

Design rules (authoritative):

- **Only structured metadata.** A conflict is created exclusively from a turn's
  ``conflict_assertions``. A turn with no assertions (or a malformed one that
  could not be parsed) contributes no conflict — that is the fail-closed path
  for missing metadata.
- **Stable IDs.** A new conflict's ``conflict_id`` is a deterministic
  ``conflict-<digest>`` derived from ``(normalized topic, kind)`` via SHA-1, so
  the same disagreement always maps to the same ID across rounds and runs. An
  assertion that carries an explicit ``conflict_id`` (for resolve/escalate, or
  to re-assert a known one) matches on that exact ID.
- **Evidence validation (fail closed).** An asserted conflict only becomes valid
  when *every* evidence ID it cites is known to the gate manifest, is High/Medium
  quality, and is observed on or before the target date. A conflict whose cited
  evidence contains an unknown, low-quality, or future ID is **not** created
  (and an already-open conflict, on re-observation with bad evidence, is dropped
  rather than kept open on unverifiable footing). Empty evidence on a NEW
  factual/interpretive conflict is also not sufficient to create it.
- **Deduplication.** A conflict is considered "the same" as a tracked one when
  their IDs match; re-observation updates ``last_seen_round``, unions valid
  evidence IDs, merges the opposing claims, and raises severity to the highest
  seen. It does not create a duplicate record.
- **Action-only never blocks.** An ``ACTION`` conflict is tracked (so the
  Research Manager can weigh the divergent recommendations) but is excluded from
  ``blocks_termination``.
- **Resolution & escalation.** A ``resolve`` / ``escalate`` assertion closes or
  promotes the referenced open conflict, recording the human-readable reason.
  Resolving a conflict that is not open is a no-op; escalating is only valid for
  an open conflict.

The tracker is pure and JSON-safe: it consumes and returns plain dicts (the
serialized ``ConflictRecord`` forms) so the result survives LangGraph
checkpointing, and it never touches the network, a clock, or an LLM.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from tradingagents.debate.evidence_manifest import EvidenceManifest
from tradingagents.debate.models import (
    ConflictAction,
    ConflictAssertion,
    ConflictKind,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    ConflictSummary,
    DebateTurn,
)

# Severity precedence for merging (critical > major > minor).
_SEVERITY_ORDER: dict[ConflictSeverity, int] = {
    ConflictSeverity.MINOR: 0,
    ConflictSeverity.MAJOR: 1,
    ConflictSeverity.CRITICAL: 2,
}


def _normalized_topic(topic: str) -> str:
    """Deterministic canonical key for a conflict topic."""
    return " ".join(str(topic or "").strip().lower().split())


def conflict_id_for(topic: str, kind: ConflictKind) -> str:
    """Stable deterministic conflict ID derived from ``(topic, kind)``.

    The same disagreement always maps to the same ID, independent of round,
    clock, or insertion order (INV-5). SHA-1 of the canonical key is truncated
    to 16 hex chars for a compact, human-readable, stable identifier.
    """
    key = f"{_normalized_topic(topic)}::{ConflictKind(kind).value}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"conflict-{digest[:16]}"


def _split_set(items: Sequence[str] | None) -> list[str]:
    """Deduplicated stable list of non-empty strings."""
    out: list[str] = []
    for item in items or []:
        item = str(item or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def _merge_participants(existing: list[str], assertion_speaker: str) -> list[str]:
    participants = _split_set(existing)
    speaker = str(assertion_speaker or "").strip()
    if speaker and speaker not in participants:
        participants.append(speaker)
    return participants or ["Bull", "Bear"]


def _validate_evidence(
    evidence_ids: Sequence[str],
    manifest: EvidenceManifest,
    target_date: str | None,
) -> tuple[list[str], bool]:
    """Partition ``evidence_ids`` into valid and invalid, and report validity.

    A cited ID is valid only when it is known, High/Medium, and observed on or
    before ``target_date``. Any ID failing these rules makes the persisted
    evidence set invalid for the purpose of *creating* a conflict, so the caller
    can fail closed (return ``created=False``).
    """
    valid: list[str] = []
    invalid: list[str] = []
    for eid in _split_set(evidence_ids):
        if (
            manifest.is_known(eid)
            and manifest.is_valid_status(eid)
            and manifest.observed_at_not_later_than(eid, target_date)
        ):
            valid.append(eid)
        else:
            invalid.append(eid)
    return valid, invalid


def _can_create(assertion: ConflictAssertion, valid_evidence: list[str], invalid: list[str]) -> bool:
    """Whether an ``assert`` with the given evidence may create a conflict.

    Fail closed: a new factual/interpretive conflict is only valid when it cites
    at least one valid evidence ID and **no** invalid (unknown/low/future) ID.
    An ACTION conflict may be tracked even without valid evidence (the divergent
    action itself is the observable disagreement), but never with an invalid ID.
    """
    if invalid:
        return False
    if assertion.kind == ConflictKind.ACTION:
        return True
    return bool(valid_evidence)


def _merge_claims(existing: ConflictRecord, assertion: ConflictAssertion) -> tuple[str, str]:
    """Merge an assertion's claims into the tracked record (prefer non-empty)."""
    bull_claim = existing.bull_claim
    bear_claim = existing.bear_claim
    if assertion.action == ConflictAction.ASSERT:
        # An assertion is authored by one side; keep the side-specific claim and
        # fill the opposing claim from the other side when asserted separately.
        if assertion.bull_claim:
            bull_claim = assertion.bull_claim
        if assertion.bear_claim:
            bear_claim = assertion.bear_claim
    return (bull_claim or existing.bull_claim, bear_claim or existing.bear_claim)


def _resolve_assert(
    *,
    assertion: ConflictAssertion,
    existing: ConflictRecord | None,
    round_index: int,
    manifest: EvidenceManifest,
    target_date: str | None,
    speakers: list[str],
) -> ConflictRecord | None:
    """Create a new conflict, or update an existing (deduplicated) one.

    Returns ``None`` when the assertion cannot produce a valid, currently
    supported conflict (fail closed). ``None`` has two meanings the caller
    distinguishes by whether ``existing`` was ``None``:

    - a NEW assertion that cannot be created (no valid evidence, or an
      unknown/low/future ID) -> no conflict is added;
    - a RE-observation that cites an unknown/low/future ID -> the previously
      open conflict is **dropped**, because keeping it open would rely on
      evidence that is no longer verifiable (see the module docstring).

    When ``existing`` is not ``None`` and the assertion names only valid
    evidence, the record is updated (merged evidence/claims, raised severity,
    advanced ``last_seen_round``/participants) and stays open unless it was
    explicitly resolved/escalated earlier.
    """
    if assertion.action != ConflictAction.ASSERT:
        return existing

    valid_evidence, invalid = _validate_evidence(assertion.evidence_ids, manifest, target_date)

    if existing is None:
        # A brand-new conflict: must pass the fail-closed create rule.
        if not _can_create(assertion, valid_evidence, invalid):
            return None
        conflict_id = assertion.conflict_id or conflict_id_for(assertion.topic, assertion.kind)
        return ConflictRecord(
            conflict_id=conflict_id,
            topic=str(assertion.topic or "").strip(),
            bull_claim=str(assertion.bull_claim or "").strip(),
            bear_claim=str(assertion.bear_claim or "").strip(),
            evidence_ids=valid_evidence,
            kind=assertion.kind,
            severity=assertion.severity,
            status=ConflictStatus.OPEN,
            participants=speakers,
            first_seen_round=round_index,
            last_seen_round=round_index,
        )

    # Re-observation of an already-tracked conflict. Fail closed on evidence:
    # if the re-observation cites ANY unknown/low/future ID, the conflict is no
    # longer on verifiable footing and is dropped rather than kept open.
    if invalid:
        return None

    # Union evidence (valid only), merge claims, raise severity, update
    # last_seen_round and participants, and stay open unless it was explicitly
    # resolved/escalated earlier.
    merged_evidence = _split_set(existing.evidence_ids + valid_evidence)
    bull_claim, bear_claim = _merge_claims(existing, assertion)
    severity = existing.severity
    if _SEVERITY_ORDER.get(assertion.severity, 0) > _SEVERITY_ORDER.get(severity, 0):
        severity = assertion.severity
    return ConflictRecord(
        conflict_id=existing.conflict_id,
        topic=existing.topic or str(assertion.topic or "").strip(),
        bull_claim=bull_claim,
        bear_claim=bear_claim,
        evidence_ids=merged_evidence,
        kind=existing.kind,
        severity=severity,
        status=existing.status,
        participants=_merge_participants(existing.participants, speakers[-1] if speakers else ""),
        first_seen_round=existing.first_seen_round,
        last_seen_round=round_index,
        resolution_reason=existing.resolution_reason,
        escalation_reason=existing.escalation_reason,
    )


def _resolve_state_update(
    *,
    assertion: ConflictAssertion,
    existing: ConflictRecord | None,
    round_index: int,
) -> ConflictRecord | None:
    """Apply a ``resolve`` / ``escalate`` action to an existing conflict."""
    if existing is None or assertion.action not in (ConflictAction.RESOLVE, ConflictAction.ESCALATE):
        return existing

    if assertion.action == ConflictAction.RESOLVE:
        if existing.status != ConflictStatus.OPEN:
            return existing  # already resolved/escalated — no-op
        return ConflictRecord(
            conflict_id=existing.conflict_id,
            topic=existing.topic,
            bull_claim=existing.bull_claim,
            bear_claim=existing.bear_claim,
            evidence_ids=list(existing.evidence_ids),
            kind=existing.kind,
            severity=existing.severity,
            status=ConflictStatus.RESOLVED,
            participants=list(existing.participants),
            first_seen_round=existing.first_seen_round,
            last_seen_round=round_index,
            resolution_reason=str(assertion.reason or "").strip(),
            escalation_reason=existing.escalation_reason,
        )

    # ESCALATE: only an open conflict can be escalated; a resolved one stays resolved.
    if existing.status == ConflictStatus.RESOLVED:
        return existing
    return ConflictRecord(
        conflict_id=existing.conflict_id,
        topic=existing.topic,
        bull_claim=existing.bull_claim,
        bear_claim=existing.bear_claim,
        evidence_ids=list(existing.evidence_ids),
        kind=existing.kind,
        severity=existing.severity,
        status=ConflictStatus.ESCALATED_TO_MANAGER,
        participants=list(existing.participants),
        first_seen_round=existing.first_seen_round,
        last_seen_round=round_index,
        resolution_reason=existing.resolution_reason,
        escalation_reason=str(assertion.reason or "").strip(),
    )


def _by_id(conflicts: Sequence[ConflictRecord]) -> dict[str, ConflictRecord]:
    return {c.conflict_id: c for c in conflicts}


def derive_conflicts(
    *,
    round_index: int,
    turns: Sequence[Any],
    manifest: EvidenceManifest,
    target_date: str | None,
    tracked: Sequence[Any] | None = None,
) -> tuple[list[ConflictRecord], list[str]]:
    """Derive the updated, deduplicated conflict list for a completed round.

    Consumes a round's ``DebateTurn`` objects (both sides are expected in a
    completed Bull->Bear pair; the caller is responsible for passing only a
    complete round). Each turn's ``conflict_assertions`` are applied in a stable
    order (Bull then Bear), creating / observing / resolving / escalating
    conflicts against the previously ``tracked`` records.

    A turn with no ``conflict_assertions`` contributes nothing — the fail-closed
    path for missing metadata (no conflict is guessed).

    Args:
        round_index: The 1-based completed round being processed.
        turns: The round's turns (in speech order). Only the structured
            ``conflict_assertions`` are read — never prose or chain-of-thought.
        manifest: The gate's :class:`EvidenceManifest` (for evidence validation).
        target_date: The requested trade date (for point-in-time validation).
        tracked: Previously tracked :class:`ConflictRecord` objects.

    Returns:
        A ``(conflicts, resolution_notes)`` pair. ``conflicts`` is the ordered
        list of :class:`ConflictRecord` objects after applying all of the round's
        assertions; ``resolution_notes`` is the ordered list of human-readable
        resolve/escalate reasons emitted in this round. Deterministic given its
        inputs.
    """
    tracked_conflicts: list[ConflictRecord] = []
    for entry in tracked or []:
        try:
            if isinstance(entry, ConflictRecord):
                record = entry
            elif isinstance(entry, Mapping):
                record = ConflictRecord.from_dict(dict(entry))
            else:
                continue
        except (TypeError, ValueError, KeyError, AttributeError):
            # A malformed / non-record entry is skipped (fail closed): a conflict
            # we cannot read is not kept, rather than guessing its meaning.
            continue
        # A tracked conflict must have a stable identity; an empty-ID record is
        # skipped rather than treated as a real tracked conflict.
        if record.conflict_id:
            tracked_conflicts.append(record)
    by_id = _by_id(tracked_conflicts)
    ordered_ids = [c.conflict_id for c in tracked_conflicts]
    resolution_notes: list[str] = []

    for turn in turns:
        if turn is None or not hasattr(turn, "conflict_assertions"):
            continue
        speaker = getattr(turn, "speaker", "")
        for raw_assertion in turn.conflict_assertions:
            # Normalize a serialized dict or an already-typed assertion; drop a
            # malformed one (fail closed — no conflict is guessed).
            if isinstance(raw_assertion, ConflictAssertion):
                assertion = raw_assertion
            elif isinstance(raw_assertion, Mapping):
                try:
                    assertion = ConflictAssertion.from_dict(dict(raw_assertion))
                except (TypeError, ValueError, KeyError, AttributeError):
                    continue
            else:
                continue
            if assertion.action == ConflictAction.ASSERT:
                existing = by_id.get(assertion.conflict_id) if assertion.conflict_id else None
                if existing is None:
                    conflict_id = assertion.conflict_id or conflict_id_for(
                        assertion.topic, assertion.kind
                    )
                    existing = by_id.get(conflict_id)
                updated = _resolve_assert(
                    assertion=assertion,
                    existing=existing,
                    round_index=round_index,
                    manifest=manifest,
                    target_date=target_date,
                    speakers=[speaker] if speaker else ["Bull", "Bear"],
                )
                if updated is None and existing is not None:
                    # Fail closed: a re-observation with unknown/low/future
                    # evidence drops the previously-open conflict.
                    dropped_id = existing.conflict_id
                    by_id.pop(dropped_id, None)
                    ordered_ids = [cid for cid in ordered_ids if cid != dropped_id]
                elif updated is not None:
                    by_id[updated.conflict_id] = updated
                    if updated.conflict_id not in ordered_ids:
                        ordered_ids.append(updated.conflict_id)
            elif assertion.action in (ConflictAction.RESOLVE, ConflictAction.ESCALATE):
                existing = by_id.get(assertion.conflict_id) if assertion.conflict_id else None
                updated = _resolve_state_update(
                    assertion=assertion,
                    existing=existing,
                    round_index=round_index,
                )
                if updated is not None:
                    by_id[updated.conflict_id] = updated
                    # Record the reason only when the status actually transitioned
                    # out of OPEN; a no-op resolve/escalate of an already-closed
                    # conflict should not emit a second, misleading note.
                    prior_status = existing.status if existing is not None else None
                    if updated.status != prior_status and updated.status != ConflictStatus.OPEN:
                        note_kind = (
                            "resolved"
                            if updated.status == ConflictStatus.RESOLVED
                            else "escalated"
                        )
                        note = f"{updated.conflict_id}: {note_kind} ({assertion.reason})"
                        if note not in resolution_notes:
                            resolution_notes.append(note)

    final = [by_id[cid] for cid in ordered_ids if cid in by_id]
    return final, resolution_notes


def build_conflict_summary(
    conflicts: Sequence[Any],
    resolution_notes: Sequence[str] | None = None,
    *,
    conflict_summary: Mapping[str, Any] | None = None,
) -> ConflictSummary:
    """Build a safe, structured, prose-free summary for the Research Manager.

    ``open_blocking_count`` is always recomputed from ``conflicts`` (authoritative)
    — it counts only conflicts whose ``blocks_termination`` is True (open
    critical/major factual or interpretive). ``conflicts`` carries the auditable
    records. ``resolution_notes`` carries the resolve/escalate reasons emitted
    along the way; when not supplied directly, they are recovered from the
    persisted ``conflict_summary`` mapping so a previously-derived summary (that
    already recorded the notes) is not downgraded to an empty one.
    """
    records: list[ConflictRecord] = []
    for c in conflicts or []:
        try:
            record = (
                c if isinstance(c, ConflictRecord) else ConflictRecord.from_dict(c)
            )
        except (TypeError, ValueError, KeyError, AttributeError):
            # A malformed conflict is never reported to the manager (fail closed).
            continue
        if record.conflict_id:
            records.append(record)
    blocking = sum(1 for c in records if c.blocks_termination())
    if not resolution_notes and isinstance(conflict_summary, Mapping):
        persisted_notes = conflict_summary.get("resolution_notes") or []
        if persisted_notes:
            resolution_notes = [str(n) for n in persisted_notes if n]
    notes = [str(n) for n in (resolution_notes or []) if n]
    return ConflictSummary(
        open_blocking_count=blocking,
        conflicts=records,
        resolution_notes=notes,
    )


def track_round_conflicts(
    *,
    state: Mapping[str, Any],
    round_turns: Sequence[DebateTurn],
    round_index: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Runtime helper: derive conflicts from state + a round's turns.

    Reads the evidence records and target date off the state, derives the updated
    conflict list and the resolution notes from the round's turns, and returns
    ``(serialized_conflicts, resolution_notes)`` ready to be written back to
    ``investment_debate_state["conflicts"]`` / the conflict summary. Purely
    deterministic and JSON-safe.
    """
    records_raw = state.get("data_quality_evidence_records") or []
    manifest = EvidenceManifest.from_records(list(records_raw))
    target_date = state.get("trade_date")
    debate = state.get("investment_debate_state") or {}
    tracked_raw = list(debate.get("conflicts") or [])
    updated, notes = derive_conflicts(
        round_index=round_index,
        turns=round_turns,
        manifest=manifest,
        target_date=target_date,
        tracked=tracked_raw,
    )
    return [c.to_dict() for c in updated], notes
