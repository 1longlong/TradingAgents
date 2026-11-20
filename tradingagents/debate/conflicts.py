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
    invalid_claimed_ids: set[str] | None = None,
) -> tuple[list[str], bool]:
    """Partition ``evidence_ids`` into valid and invalid, and report validity.

    A cited ID is valid only when it is known, High/Medium, and observed on or
    before ``target_date``. Any ID failing these rules makes the persisted
    evidence set invalid for the purpose of *creating* a conflict, so the caller
    can fail closed (return ``created=False``).

    ADR-010: an ID targeted by an exact claim that did not validate (a wrong
    date/value/unit, ``invalid_claimed_ids``) is treated as invalid here, so a
    factual conflict is neither created nor kept open on a valid-but-misused
    citation. An ID with no exact claim at all is unaffected.
    """
    invalid_claimed = set(invalid_claimed_ids or ())
    valid: list[str] = []
    invalid: list[str] = []
    for eid in _split_set(evidence_ids):
        if eid in invalid_claimed:
            invalid.append(eid)
        elif (
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
    invalid_claimed_ids: set[str] | None = None,
) -> tuple[ConflictRecord | None, bool]:
    """Create a new conflict, or update an existing (deduplicated) one.

    Returns ``(record, denied)``:

    - ``(None, False)`` — a NEW assertion that cannot be created (no valid
      evidence, or an unknown/low/future/wrong-claim ID): no conflict is added;
    - ``(existing, True)`` — a RE-observation that cites unknown/low/future or a
      valid-but-misused exact claim. The attempted observation is REJECTED and the
      previously tracked record is **kept unchanged** (open/escalated history is
      preserved, never erased); a validation denial is recorded by the caller;
    - ``(updated, False)`` — a valid re-observation (merged evidence/claims,
      raised severity, advanced round/participants) or a brand-new conflict.

    A bad citation can therefore never *erase* an open factual conflict (which
    would let bad evidence manufacture convergence); it can only fail to add
    support.
    """
    if assertion.action != ConflictAction.ASSERT:
        return existing, False

    valid_evidence, invalid = _validate_evidence(
        assertion.evidence_ids, manifest, target_date, invalid_claimed_ids
    )

    if existing is None:
        # A brand-new conflict: must pass the fail-closed create rule.
        if not _can_create(assertion, valid_evidence, invalid):
            return None, False
        conflict_id = assertion.conflict_id or conflict_id_for(assertion.topic, assertion.kind)
        return (
            ConflictRecord(
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
            ),
            False,
        )

    # Re-observation of an already-tracked conflict. A re-observation that cites
    # ANY unknown/low/future/wrong-claim ID is REJECTED, but it must NOT erase the
    # prior open/escalated record: keep ``existing`` unchanged and record a denial.
    if invalid:
        return existing, True

    # Union evidence (valid only), merge claims, raise severity, update
    # last_seen_round and participants, and stay open unless it was explicitly
    # resolved/escalated earlier.
    merged_evidence = _split_set(existing.evidence_ids + valid_evidence)
    bull_claim, bear_claim = _merge_claims(existing, assertion)
    severity = existing.severity
    if _SEVERITY_ORDER.get(assertion.severity, 0) > _SEVERITY_ORDER.get(severity, 0):
        severity = assertion.severity
    return (
        ConflictRecord(
            conflict_id=existing.conflict_id,
            topic=existing.topic or str(assertion.topic or "").strip(),
            bull_claim=bull_claim,
            bear_claim=bear_claim,
            evidence_ids=merged_evidence,
            kind=existing.kind,
            severity=severity,
            status=existing.status,
            participants=_merge_participants(
                existing.participants, speakers[-1] if speakers else ""
            ),
            first_seen_round=existing.first_seen_round,
            last_seen_round=round_index,
            resolution_reason=existing.resolution_reason,
            escalation_reason=existing.escalation_reason,
        ),
        False,
    )


def _resolve_state_update(
    *,
    assertion: ConflictAssertion,
    existing: ConflictRecord | None,
    round_index: int,
    manifest: EvidenceManifest | None = None,
    target_date: str | None = None,
    invalid_claimed_ids: set[str] | None = None,
) -> tuple[ConflictRecord | None, bool]:
    """Apply a ``resolve`` / ``escalate`` action to an existing conflict.

    Returns ``(record, denied)``. An attempted RESOLVE/ESCALATE that cites
    **invalid** evidence (unknown/low/future or a valid-but-misused exact claim)
    is REJECTED: the prior open/escalated record is kept unchanged and
    ``denied=True`` is returned, so a bad citation can never manufacture
    convergence by closing an open conflict. Resolve/escalate with no evidence
    cited keeps the existing (already-audited) evidence on the record and is
    allowed as before.
    """
    if existing is None or assertion.action not in (ConflictAction.RESOLVE, ConflictAction.ESCALATE):
        return existing, False

    # Reject a resolution/escalation whose NEW cited evidence is invalid; never
    # close an open conflict on unverifiable footing.
    if manifest is not None and assertion.evidence_ids:
        _valid, invalid = _validate_evidence(
            assertion.evidence_ids, manifest, target_date, invalid_claimed_ids
        )
        if invalid:
            return existing, True

    if assertion.action == ConflictAction.RESOLVE:
        if existing.status != ConflictStatus.OPEN:
            return existing, False  # already resolved/escalated — no-op
        return (
            ConflictRecord(
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
            ),
            False,
        )

    # ESCALATE: only an open conflict can be escalated; a resolved one stays resolved.
    if existing.status == ConflictStatus.RESOLVED:
        return existing, False
    return (
        ConflictRecord(
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
        ),
        False,
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
    invalid_claimed_ids: set[str] | None = None,
    denials: list[str] | None = None,
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
        resolve/escalate reasons emitted in this round. When ``denials`` is supplied
        it is populated (in stable order) with auditable denial reasons for an
        assertion/resolution that cited invalid evidence — the prior
        open/escalated record is KEPT, never erased by a bad citation. Deterministic
        given its inputs.
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
    local_denials: list[str] = []

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
                updated, denied = _resolve_assert(
                    assertion=assertion,
                    existing=existing,
                    round_index=round_index,
                    manifest=manifest,
                    target_date=target_date,
                    speakers=[speaker] if speaker else ["Bull", "Bear"],
                    invalid_claimed_ids=invalid_claimed_ids,
                )
                if denied and existing is not None:
                    # A bad re-observation is REJECTED: the previously-tracked
                    # open/escalated conflict is KEPT unchanged (never erased), and
                    # an auditable denial is recorded. Bad evidence can never
                    # manufacture convergence by dropping a dispute.
                    _record_denial(
                        local_denials,
                        f"{existing.conflict_id}: observation_rejected "
                        f"(invalid evidence; prior {existing.status.value} record kept)",
                    )
                elif updated is not None:
                    by_id[updated.conflict_id] = updated
                    if updated.conflict_id not in ordered_ids:
                        ordered_ids.append(updated.conflict_id)
                # A NEW assertion that could not be created (updated is None and
                # existing is None) contributes nothing (fail closed) — no denial
                # for a dispute that was never tracked.
            elif assertion.action in (ConflictAction.RESOLVE, ConflictAction.ESCALATE):
                existing = by_id.get(assertion.conflict_id) if assertion.conflict_id else None
                updated, denied = _resolve_state_update(
                    assertion=assertion,
                    existing=existing,
                    round_index=round_index,
                    manifest=manifest,
                    target_date=target_date,
                    invalid_claimed_ids=invalid_claimed_ids,
                )
                if denied and existing is not None:
                    # A resolution/escalation on invalid evidence is REJECTED; the
                    # prior open/escalated record is kept and a denial is recorded,
                    # so a bad citation can never close a dispute (false consensus).
                    _record_denial(
                        local_denials,
                        f"{existing.conflict_id}: "
                        f"{assertion.action.value}_rejected "
                        f"(invalid evidence; prior {existing.status.value} record kept)",
                    )
                elif updated is not None:
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
    if denials is not None:
        for d in local_denials:
            if d not in denials:
                denials.append(d)
    return final, resolution_notes


def _record_denial(denials: list[str], note: str) -> None:
    """Append a denial reason once (stable order)."""
    if note not in denials:
        denials.append(note)


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
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Runtime helper: derive conflicts from state + a round's turns.

    Reads the evidence records and target date off the state, derives the updated
    conflict list, resolution notes and invalid-evidence denials from the round's
    turns, and returns ``(serialized_conflicts, resolution_notes, denials)`` ready
    to be written back to ``investment_debate_state["conflicts"]`` / the conflict
    summary. Purely deterministic and JSON-safe.
    """
    records_raw = state.get("data_quality_evidence_records") or []
    manifest = EvidenceManifest.from_records(list(records_raw))
    target_date = state.get("trade_date")
    debate = state.get("investment_debate_state") or {}
    tracked_raw = list(debate.get("conflicts") or [])
    # ADR-010: reject a factual conflict whose supporting citation is a valid ID
    # carrying a wrong date/value/unit exact claim.
    from tradingagents.debate.claims import claimed_ids_with_failed_claims
    from tradingagents.evidence.origin import origin_records_from_state

    records_by_id = {
        str(r.get("evidence_id", "")): r
        for r in records_raw
        if isinstance(r, Mapping) and r.get("evidence_id")
    }
    invalid_claimed_ids = claimed_ids_with_failed_claims(
        list(round_turns),
        origin_by_id=origin_records_from_state(dict(state)),
        records_by_id=records_by_id,
        target_date=target_date,
        expected_symbol=str(state.get("company_of_interest", "") or ""),
    )
    updated, notes, denials = derive_conflicts(
        round_index=round_index,
        turns=round_turns,
        manifest=manifest,
        target_date=target_date,
        tracked=tracked_raw,
        invalid_claimed_ids=invalid_claimed_ids,
    )
    return [c.to_dict() for c in updated], notes, denials
