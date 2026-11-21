"""Request/run-scoped capture of structured, vendor-origin evidence.

This module holds the typed *side channel* the Data Quality Gate reads to ingest
optional-category evidence (``fundamentals``, ``news``, ``sentiment``) that was
actually returned by a configured data vendor, without parsing analyst prose and
without trusting a model-written record.

Design rules (authoritative, see ADR-008):

- **Request/run-scoped, never a global cache.** The active collector is a
  ``ContextVar`` so two concurrent runs in the same process cannot see each
  other's records, and a fresh run resets it. There is no module-level mutable
  evidence cache.
- **Durable across tool-node execution AND checkpoint/resume.** LangChain's tool
  executor copies the context into worker threads, so capture reaches the tool
  functions; and every capture is *also* flushed into ``AgentState`` at the
  tool-node boundary (via :func:`merge_into_state`) so a checkpoint taken after a
  tool node carries the records, and a resumed run re-seeds the collector from
  that state (via :func:`seed_from_state`). The ContextVar alone is not durable;
  the state channel is.
- **Typed origin data only.** Vendor functions capture the typed
  :class:`~tradingagents.evidence.models.EvidenceRecord`s they create *before*
  formatting a public prose string. The capture is a side effect; every public
  return type/prose is unchanged (backward compatible).
- **Deterministic + de-duplicated.** Records keep a deterministic
  ``evidence_id``; capturing the same record twice (e.g. a repeated checkpoint
  resume) is a no-op. Capture order is stable; consumers sort deterministically.
- **Source attempts are real or absent, with explicit identity.** A
  ``SourceAttempt`` is recorded only for a source the run actually operated. Each
  attempt carries an explicit per-run sequence ``attempt_index`` inside a
  versioned envelope (:class:`AttemptEnvelope`), so two genuinely distinct
  attempts with ``started_at=None`` (e.g. two StockTwits calls) are **both**
  kept; only a true re-sync of the *same* already-seeded attempt (identified by
  its stable ``attempt_index``) is dropped. No attempt is invented for a feed the
  run never called.
- **JSON-safe and sanitized.** Everything stored here serializes via ``to_dict``;
  the gate turns it into plain dicts before writing state. Error text and
  provenance are sanitized upstream (no URL query strings, usernames, keys or
  bodies) by the adapters.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from tradingagents.evidence.models import EvidenceRecord, SourceAttempt
from tradingagents.evidence.origin import (
    ORIGIN_CONFLICTED_STATE_KEY,
    ORIGIN_DROPPED_STATE_KEY,
    ORIGIN_STATE_KEY,
    OriginMetadata,
    serialize_origin_map,
)

# The provenance contract version emitted with captured data. Versioned so an
# audit can tell which capture semantics produced a record/envelope.
CAPTURE_SCHEMA_VERSION = "1.2"

# The state keys the gate exposes (document the JSON-safe envelope). The attempt
# ledger the report/gate consumes is the bare 7-field list
# (``data_quality_source_attempts``); the durable envelope channel (which carries
# the explicit ``attempt_index`` identity so distinct attempts never collapse) is
# kept under a SEPARATE key so the two never collide.
INGEST_RECORDS_STATE_KEY = "data_quality_ingested_evidence"
INGEST_ATTEMPTS_STATE_KEY = "data_quality_source_attempt_envelopes"
INGEST_METADATA_STATE_KEY = "data_quality_ingest_metadata"
INGEST_NOT_ATTEMPTED_STATE_KEY = "data_quality_not_attempted_feeds"
INGEST_DROPPED_STATE_KEY = ORIGIN_DROPPED_STATE_KEY

# Defect-1 (ADR-010 amendment): evidence ids whose origin metadata was captured
# MORE THAN ONCE with different values, or which otherwise lost origin trust. The
# gate merge fails these ids closed (unverified/ambiguous) rather than silently
# accepting a first/last-wins origin. Declared on AgentState so a checkpoint and a
# resumed run retain the ambiguity instead of silently re-trusting an origin.
# The canonical key lives in ``origin`` (so the read choke point can filter it
# without an import cycle); re-exported here for the ingest/graph call sites.
INGEST_ORIGIN_CONFLICTED_STATE_KEY = ORIGIN_CONFLICTED_STATE_KEY


@dataclass
class IngestMetadata:
    """Run-scoped identifiers recorded with captured evidence.

    ``symbol`` / ``target_date`` are the run's canonical symbol and requested
    analysis date, set once at run start. ``next_attempt_index`` is the next
    explicit source-attempt identity to hand out (monotonic per run). Plain
    JSON-safe fields only.
    """

    symbol: str = ""
    target_date: str = ""
    next_attempt_index: int = 0
    schema_version: str = CAPTURE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "target_date": self.target_date,
            "next_attempt_index": self.next_attempt_index,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> IngestMetadata:
        data = data or {}
        try:
            next_index = int(data.get("next_attempt_index", 0) or 0)
        except (TypeError, ValueError):
            next_index = 0
        return cls(
            symbol=str(data.get("symbol", "") or ""),
            target_date=str(data.get("target_date", "") or ""),
            next_attempt_index=max(0, next_index),
            schema_version=str(data.get("schema_version", CAPTURE_SCHEMA_VERSION)),
        )


@dataclass(frozen=True)
class AttemptEnvelope:
    """Versioned, JSON-safe wrapper giving each captured attempt explicit identity.

    The 7-field :class:`~tradingagents.evidence.models.SourceAttempt` is preserved
    unchanged (never extended); the *envelope* adds a documented per-run
    ``attempt_index`` so two distinct attempts that happen to share identical
    structural fields (e.g. both with ``started_at=None``) remain two entries.
    """

    attempt_index: int
    attempt: SourceAttempt
    schema_version: str = CAPTURE_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "attempt_index": self.attempt_index,
            "schema_version": self.schema_version,
            "attempt": self.attempt.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AttemptEnvelope:
        return cls(
            attempt_index=int(data.get("attempt_index", 0) or 0),
            attempt=SourceAttempt.from_dict(dict(data.get("attempt") or {})),
            schema_version=str(data.get("schema_version", CAPTURE_SCHEMA_VERSION)),
        )


def _origin_canonical(origin: OriginMetadata) -> str:
    """A stable canonical string for an origin (conflict detection only).

    Only the typed, JSON-safe origin fields are serialized (no record body/prompt/
    secret). Two captured origins for the same id are "conflicting" iff this
    differs.
    """
    import json

    try:
        return json.dumps(origin.to_dict(), sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 — an unserializable origin is treated as unique
        return repr(origin)


def _origin_dict_canonical(origin: Mapping[str, Any]) -> str:
    """Canonical string for an already-serialized origin dict (conflict detection)."""
    import json

    try:
        return json.dumps(dict(origin), sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 — an unserializable origin is treated as unique
        return repr(origin)


@dataclass
class StructuredEvidenceCollector:
    """Accumulates typed evidence records and source attempts for one run.

    A collector is created per run (via :func:`use_collector`) and is never
    shared across runs. Capturing a record with an already-seen ``evidence_id``
    is a no-op; attempts receive a fresh explicit ``attempt_index`` so distinct
    attempts never collapse, while :meth:`seed_*` (resume) restores exact prior
    identities without duplicating them.
    """

    metadata: IngestMetadata = field(default_factory=IngestMetadata)
    _records: dict[str, EvidenceRecord] = field(default_factory=dict)
    # ADR-010: typed origin/date-role/unit semantics keyed by evidence id. Kept
    # separate from the locked 20-field record; captured alongside it.
    _origins: dict[str, OriginMetadata] = field(default_factory=dict)
    # Defect-1: ids for which TWO genuinely different origins were captured. The
    # conflict is RETAINED (not collapsed by first/last-wins) so the gate merge can
    # fail the id closed (unverified/ambiguous) instead of trusting one origin.
    _conflicted_origin_ids: set[str] = field(default_factory=set)
    _attempts: list[AttemptEnvelope] = field(default_factory=list)
    _attempt_indices: set[int] = field(default_factory=set)
    _not_attempted: list[str] = field(default_factory=list)
    # Explicit tombstone: records excluded at the gate are DROPPED and their ids
    # recorded so a later merge/resume can never resurrect them as evidence
    # (a prune-then-union would otherwise pull a persisted excluded record back).
    _dropped_record_ids: set[str] = field(default_factory=set)
    # Guards attempt-index allocation and record/attempt mutation, because the
    # shared collector is reached from multiple LangChain tool worker threads
    # concurrently. Never part of serialization.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # -- capture ---------------------------------------------------------

    def seed(self, symbol: str, target_date: str) -> None:
        """Record the run identity (canonical symbol + requested date)."""
        self.metadata = IngestMetadata(
            symbol=str(symbol or ""),
            target_date=str(target_date or ""),
            next_attempt_index=self.metadata.next_attempt_index,
        )

    def capture_record(self, record: EvidenceRecord) -> None:
        """Store one typed evidence record (idempotent by ``evidence_id``)."""
        evidence_id = record.evidence_id
        if not evidence_id:
            return
        with self._lock:
            self._records.setdefault(evidence_id, record)

    def capture_origin(self, evidence_id: str, origin: OriginMetadata) -> None:
        """Store typed origin metadata for one evidence id.

        Idempotent for an IDENTICAL re-capture. A genuinely DIFFERENT origin for
        the same id is a real conflict: it is RETAINED as conflicted (never
        silently collapsed by first/last-wins) so the gate merge fails the id
        closed (unverifiable). The first origin remains the retained value; the
        conflict set records that it is untrustworthy. Never invents a value.
        """
        if not evidence_id or origin is None:
            return
        with self._lock:
            existing = self._origins.get(evidence_id)
            if existing is None:
                self._origins[evidence_id] = origin
                return
            if _origin_canonical(existing) != _origin_canonical(origin):
                # A different origin for the same deterministic id is a conflict;
                # keep the id untrusted (fail closed) instead of last-wins.
                self._conflicted_origin_ids.add(evidence_id)

    def origin_for(self, evidence_id: str) -> OriginMetadata | None:
        with self._lock:
            return self._origins.get(evidence_id)

    def origins_map(self) -> dict[str, OriginMetadata]:
        with self._lock:
            return dict(self._origins)

    def conflicted_origin_ids(self) -> set[str]:
        """Evidence ids whose captured origin conflicted (fail closed downstream)."""
        with self._lock:
            return set(self._conflicted_origin_ids)

    def capture_attempt(self, attempt: SourceAttempt) -> None:
        """Store one source attempt with a fresh explicit per-run identity.

        Distinct attempts are never collapsed (even when every structural field
        matches, e.g. ``started_at=None``): each gets the next monotonic
        ``attempt_index``. The index allocation is guarded by a lock so several
        simultaneous ToolNode calls sharing this collector cannot collide. A
        re-sync of an already-seeded index is a no-op (see :meth:`seed_attempt`).
        """
        with self._lock:
            index = self.metadata.next_attempt_index
            self.metadata.next_attempt_index = index + 1
            self._attempts.append(AttemptEnvelope(attempt_index=index, attempt=attempt))
            self._attempt_indices.add(index)

    def note_not_attempted(self, feed: str) -> None:
        """Record a configured-but-unoperated feed (explicit, non-attempt).

        This is NOT an operated attempt: it never enters the SourceAttempt ledger
        and never counts toward a source count. It is kept only as explicit
        ``not_attempted`` metadata so the audit can distinguish "we did not call
        this feed" from "we called it and it failed/returned empty".
        """
        with self._lock:
            if feed and feed not in self._not_attempted:
                self._not_attempted.append(feed)

    def not_attempted(self) -> list[str]:
        with self._lock:
            return list(self._not_attempted)

    def drop_record(self, evidence_id: str) -> None:
        """Explicitly drop a record and record a tombstone (never resurrect)."""
        if not evidence_id:
            return
        with self._lock:
            self._records.pop(evidence_id, None)
            self._dropped_record_ids.add(evidence_id)

    def dropped_record_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._dropped_record_ids)

    # -- resume (seed from persisted state without duplicating) -----------

    def seed_record(self, record: EvidenceRecord) -> None:
        """Restore a previously persisted record (idempotent by evidence_id)."""
        self.capture_record(record)

    def _identity_compatible(self, prior: IngestMetadata) -> bool:
        """True iff ``prior`` names the same run identity as this collector.

        Symbol/target-date compare case-/whitespace-insensitively (symbols are
        upper-cased elsewhere); the schema version must match exactly. A prior
        with an empty symbol/date is treated as unknown and accepted (it carries
        no conflicting identity); a mismatching non-empty value is rejected.
        """
        def norm(value: str) -> str:
            return str(value or "").strip().upper()

        if prior.schema_version and prior.schema_version != self.metadata.schema_version:
            return False
        if prior.symbol and norm(prior.symbol) != norm(self.metadata.symbol):
            return False
        return not (prior.target_date and prior.target_date != self.metadata.target_date)

    def _record_matches_identity(self, record: EvidenceRecord) -> bool:
        """True iff a persisted record belongs to this run's symbol/target/run_id."""
        def norm(value: str) -> str:
            return str(value or "").strip().upper()

        if norm(record.ticker_normalized) != norm(self.metadata.symbol):
            return False
        if (
            self.metadata.target_date
            and record.target_date
            and record.target_date != self.metadata.target_date
        ):
            return False
        if self.metadata.target_date and self.metadata.symbol:
            from tradingagents.dataflows.symbol_utils import normalize_symbol
            from tradingagents.graph.data_quality_gate import build_gate_run_id

            expected_run_id = build_gate_run_id(
                self.metadata.target_date, normalize_symbol(self.metadata.symbol)
            )
            if record.run_id and record.run_id != expected_run_id:
                return False
        return True

    def seed_attempt(self, envelope: AttemptEnvelope) -> None:
        """Restore a previously persisted attempt (idempotent by attempt_index)."""
        with self._lock:
            if envelope.attempt_index in self._attempt_indices:
                return
            self._attempt_indices.add(envelope.attempt_index)
            self._attempts.append(envelope)
            if envelope.attempt_index >= self.metadata.next_attempt_index:
                self.metadata.next_attempt_index = envelope.attempt_index + 1

    def seed_from_state(self, state: Mapping[str, Any] | None) -> None:
        """Re-seed this collector from a persisted run's state (resume-safe).

        Restores records, attempt envelopes and the run metadata so a resumed run
        continues with the same identities and never duplicates what a prior
        checkpoint already carried. Malformed entries are skipped (fail safe),
        never coerced into a fabricated record.

        **Identity guard:** if the persisted metadata names a different
        symbol/target date/schema version than the collector's current identity,
        the persisted records/attempts are NOT adopted (they belong to a foreign
        run) and the current identity is kept — a foreign checkpoint can never
        contaminate this run.
        """
        if not isinstance(state, Mapping):
            return
        meta = state.get(INGEST_METADATA_STATE_KEY)
        adopt = True
        if isinstance(meta, Mapping):
            prior = IngestMetadata.from_dict(meta)
            adopt = self._identity_compatible(prior)
            if adopt:
                # Keep the higher attempt index; keep our own non-empty symbol.
                self.metadata.next_attempt_index = max(
                    self.metadata.next_attempt_index, prior.next_attempt_index
                )
        if not adopt:
            # Foreign/mismatched persisted identity: quarantine everything.
            return
        for raw in state.get(INGEST_RECORDS_STATE_KEY) or []:
            if isinstance(raw, Mapping):
                try:
                    record = EvidenceRecord.from_dict(dict(raw))
                except Exception:  # noqa: BLE001 — a bad persisted row is skipped
                    continue
                if self._record_matches_identity(record):
                    self.seed_record(record)
        for raw in state.get(INGEST_ATTEMPTS_STATE_KEY) or []:
            if isinstance(raw, Mapping):
                try:
                    self.seed_attempt(AttemptEnvelope.from_dict(dict(raw)))
                except Exception:  # noqa: BLE001 — a bad persisted row is skipped
                    continue
        # ADR-010: restore typed origin metadata so a resumed run re-validates
        # claims against the SAME origin semantics (dates/units never re-invented).
        for evidence_id, raw in (state.get(ORIGIN_STATE_KEY) or {}).items():
            if isinstance(raw, Mapping):
                try:
                    self.capture_origin(str(evidence_id), OriginMetadata.from_dict(dict(raw)))
                except Exception:  # noqa: BLE001 — a bad persisted origin is skipped
                    continue
        for feed in state.get(INGEST_NOT_ATTEMPTED_STATE_KEY) or []:
            if isinstance(feed, str):
                self.note_not_attempted(feed)
        for dropped in state.get(INGEST_DROPPED_STATE_KEY) or []:
            if isinstance(dropped, str):
                self._dropped_record_ids.add(dropped)
                self._records.pop(dropped, None)
        # Defect-1: restore the retained origin-conflict set so a resumed run keeps
        # those ids untrusted (a checkpoint re-seed never silently re-trusts an
        # origin that conflicted on a prior attempt).
        for conflicted in state.get(INGEST_ORIGIN_CONFLICTED_STATE_KEY) or []:
            if isinstance(conflicted, str):
                self._conflicted_origin_ids.add(conflicted)

    # -- read ------------------------------------------------------------
    def has_records(self) -> bool:
        return bool(self._records)

    def records_for_category(self, category: str) -> list[EvidenceRecord]:
        """Captured records for one category, deterministically ordered by ID."""
        return sorted(
            (r for r in self._records.values() if r.category == category),
            key=lambda r: r.evidence_id,
        )

    def all_records(self) -> list[EvidenceRecord]:
        """Every captured record, deterministically ordered by ``evidence_id``."""
        return sorted(self._records.values(), key=lambda r: r.evidence_id)

    def attempts(self) -> list[SourceAttempt]:
        """Typed source-attempt ledger (attempt-index order preserved)."""
        return [env.attempt for env in sorted(self._attempts, key=lambda e: e.attempt_index)]

    def attempt_envelopes(self) -> list[AttemptEnvelope]:
        return sorted(self._attempts, key=lambda e: e.attempt_index)

    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({r.category for r in self._records.values()}))

    # -- serialization ---------------------------------------------------

    def records_to_dicts(self) -> list[dict]:
        return [r.to_dict() for r in self.all_records()]

    def attempts_to_envelope_dicts(self) -> list[dict]:
        return [env.to_dict() for env in self.attempt_envelopes()]

    def attempts_to_dicts(self) -> list[dict]:
        """The bare 7-field attempt dicts (for the report-facing envelope)."""
        return [env.attempt.to_dict() for env in self.attempt_envelopes()]

    # -- state merge (durable across checkpoint) -------------------------

    def state_delta(
        self,
        *,
        pruned_record_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """A JSON-safe state delta carrying this run's captured evidence.

        ``pruned_record_ids`` lets a caller drop records that were excluded at
        the gate so they are not re-persisted (the gate reports one via the pruned
        list). The delta is merge-safe: it re-writes the full accumulated set each
        time, so applying it to state is idempotent.
        """
        pruned = set(pruned_record_ids or ())
        records = [
            r.to_dict()
            for r in self.all_records()
            if r.evidence_id not in pruned and r.evidence_id not in self._dropped_record_ids
        ]
        dropped = sorted(self._dropped_record_ids | pruned)
        origins = {
            evidence_id: origin
            for evidence_id, origin in self._origins.items()
            if evidence_id not in pruned and evidence_id not in self._dropped_record_ids
        }
        conflicted = sorted(
            evidence_id
            for evidence_id in self._conflicted_origin_ids
            if evidence_id not in pruned and evidence_id not in self._dropped_record_ids
        )
        return {
            INGEST_RECORDS_STATE_KEY: records,
            ORIGIN_STATE_KEY: serialize_origin_map(origins),
            INGEST_ORIGIN_CONFLICTED_STATE_KEY: conflicted,
            INGEST_ATTEMPTS_STATE_KEY: self.attempts_to_envelope_dicts(),
            INGEST_METADATA_STATE_KEY: self.metadata.to_dict(),
            INGEST_NOT_ATTEMPTED_STATE_KEY: self.not_attempted(),
            INGEST_DROPPED_STATE_KEY: dropped,
        }


# The active run-scoped collector. Default ``None`` means "no run in progress",
# in which case capture call sites are silent no-ops (e.g. a bare tool test).
_ACTIVE: ContextVar[StructuredEvidenceCollector | None] = ContextVar(
    "tradingagents_active_evidence_collector", default=None
)


def get_active_collector() -> StructuredEvidenceCollector | None:
    """The collector bound to the current run context, or ``None``."""
    return _ACTIVE.get()


def capture_record(record: EvidenceRecord) -> None:
    """Capture ``record`` into the active run collector (no-op if none)."""
    collector = _ACTIVE.get()
    if collector is not None:
        collector.capture_record(record)


def capture_attempt(attempt: SourceAttempt) -> None:
    """Capture ``attempt`` into the active run collector (no-op if none)."""
    collector = _ACTIVE.get()
    if collector is not None:
        collector.capture_attempt(attempt)


def capture_origin(evidence_id: str, origin: OriginMetadata) -> None:
    """Capture typed origin metadata into the active run collector (no-op if none)."""
    collector = _ACTIVE.get()
    if collector is not None:
        collector.capture_origin(evidence_id, origin)


def merge_into_state(
    delta: Mapping[str, Any],
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge a collector state delta into existing state without dropping data.

    Records are unioned by ``evidence_id``; attempt envelopes by
    ``attempt_index``; metadata keeps the highest ``next_attempt_index``. Dropped
    (excluded) record ids are UNIONED as explicit tombstones and any record whose
    id is tombstoned on either side is removed — so a prune-then-union can never
    resurrect an excluded record. The result is JSON-safe and order-stable, so it
    is safe to return as a node's state update and to checkpoint.
    """
    merged: dict[str, Any] = {}
    incoming_records = {str(r.get("evidence_id", "")): r for r in delta.get(INGEST_RECORDS_STATE_KEY) or []}
    existing_records = {}
    if isinstance(state, Mapping):
        existing_records = {
            str(r.get("evidence_id", "")): r
            for r in state.get(INGEST_RECORDS_STATE_KEY) or []
            if isinstance(r, Mapping)
        }
    # Tombstones from both sides are authoritative: a dropped id never returns.
    dropped: set[str] = set()
    for src in (delta, state if isinstance(state, Mapping) else {}):
        for eid in (src or {}).get(INGEST_DROPPED_STATE_KEY) or []:
            if isinstance(eid, str):
                dropped.add(eid)
    combined_records = {
        eid: rec for eid, rec in existing_records.items() if eid not in dropped
    }
    # Incoming wins (it is the fresher capture of the same deterministic id),
    # unless the incoming record id is itself tombstoned.
    for eid, rec in incoming_records.items():
        if eid not in dropped:
            combined_records[eid] = rec
    merged[INGEST_RECORDS_STATE_KEY] = [
        combined_records[eid] for eid in sorted(combined_records)
    ]
    merged[INGEST_DROPPED_STATE_KEY] = sorted(dropped)

    # ADR-010 (Defect-1 amendment): origin metadata is unioned by evidence id; a
    # dropped id is excluded so a tombstoned record never keeps a stale origin. A
    # genuinely DIFFERING existing vs incoming origin for the same id is a real
    # conflict: it is RETAINED as conflicted (the id is failed closed downstream),
    # and the incoming value never silently overwrites the existing one
    # (no first/last-wins). Identical values are a harmless re-capture.
    incoming_origins = {
        str(eid): origin
        for eid, origin in (delta.get(ORIGIN_STATE_KEY) or {}).items()
        if isinstance(origin, Mapping)
    }
    existing_origins = {}
    if isinstance(state, Mapping):
        existing_origins = {
            str(eid): origin
            for eid, origin in (state.get(ORIGIN_STATE_KEY) or {}).items()
            if isinstance(origin, Mapping)
        }
    conflicted: set[str] = set()
    for src in (delta, state if isinstance(state, Mapping) else {}):
        for eid in (src or {}).get(INGEST_ORIGIN_CONFLICTED_STATE_KEY) or []:
            if isinstance(eid, str):
                conflicted.add(eid)
    combined_origins = {eid: o for eid, o in existing_origins.items() if eid not in dropped}
    for eid, origin in incoming_origins.items():
        if eid in dropped:
            continue
        if eid in combined_origins and _origin_dict_canonical(
            combined_origins[eid]
        ) != _origin_dict_canonical(origin):
            # Conflicting captured origins for the same deterministic id: fail the
            # id closed instead of adopting (or overwriting with) either side.
            conflicted.add(eid)
        else:
            combined_origins[eid] = origin
    merged[ORIGIN_STATE_KEY] = {eid: combined_origins[eid] for eid in sorted(combined_origins)}
    merged[INGEST_ORIGIN_CONFLICTED_STATE_KEY] = sorted(
        eid for eid in conflicted if eid not in dropped
    )

    incoming_attempts = {
        int(env.get("attempt_index", -1)): env
        for env in delta.get(INGEST_ATTEMPTS_STATE_KEY) or []
    }
    existing_attempts = {}
    if isinstance(state, Mapping):
        existing_attempts = {
            int(env.get("attempt_index", -1)): env
            for env in state.get(INGEST_ATTEMPTS_STATE_KEY) or []
            if isinstance(env, Mapping)
        }
    combined_attempts = {**existing_attempts}
    combined_attempts.update(incoming_attempts)
    merged[INGEST_ATTEMPTS_STATE_KEY] = [
        combined_attempts[i] for i in sorted(combined_attempts)
    ]

    delta_meta = delta.get(INGEST_METADATA_STATE_KEY) or {}
    state_meta = (state or {}).get(INGEST_METADATA_STATE_KEY) if isinstance(state, Mapping) else {}
    next_index = max(
        int((delta_meta or {}).get("next_attempt_index", 0) or 0),
        int((state_meta or {}).get("next_attempt_index", 0) or 0),
    )
    merged[INGEST_METADATA_STATE_KEY] = {
        "symbol": (delta_meta or {}).get("symbol") or (state_meta or {}).get("symbol", ""),
        "target_date": (delta_meta or {}).get("target_date")
        or (state_meta or {}).get("target_date", ""),
        "next_attempt_index": next_index,
        "schema_version": CAPTURE_SCHEMA_VERSION,
    }

    # not_attempted feeds: union, order-stable (never counted as attempts).
    delta_feeds = [f for f in delta.get(INGEST_NOT_ATTEMPTED_STATE_KEY) or [] if isinstance(f, str)]
    state_feeds = []
    if isinstance(state, Mapping):
        state_feeds = [
            f for f in state.get(INGEST_NOT_ATTEMPTED_STATE_KEY) or [] if isinstance(f, str)
        ]
    seen_feeds = list(dict.fromkeys(state_feeds + delta_feeds))
    merged[INGEST_NOT_ATTEMPTED_STATE_KEY] = seen_feeds
    return merged


@contextlib.contextmanager
def use_collector(
    symbol: str = "",
    target_date: str = "",
    prior_state: Mapping[str, Any] | None = None,
) -> Iterator[StructuredEvidenceCollector]:
    """Bind a fresh collector for the duration of one run.

    Nested/concurrent runs get independent collectors because the binding is a
    ``ContextVar``. When ``prior_state`` is supplied (a resumed run), the
    collector is re-seeded from it first so prior captured evidence survives the
    process boundary and is not duplicated. The previous binding is restored on
    exit so a test (or a caller) never leaks a collector into an unrelated run.
    """
    collector = StructuredEvidenceCollector()
    collector.seed(symbol, target_date)
    if prior_state is not None:
        collector.seed_from_state(prior_state)
        # Preserve the run identity established above even if the persisted
        # metadata lacks it (e.g. an older checkpoint).
        if not collector.metadata.symbol:
            collector.metadata.symbol = str(symbol or "")
        if not collector.metadata.target_date:
            collector.metadata.target_date = str(target_date or "")
    token = _ACTIVE.set(collector)
    try:
        yield collector
    finally:
        _ACTIVE.reset(token)
