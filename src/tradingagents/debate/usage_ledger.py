"""Durable, run-scoped usage ledger for model invocations (ADR-009).

This module is the durable backbone of Stage 2 accounting. It records, for one
*execution* (a fresh run, its resume, or a finished run) of the trading graph:

- a **reservation** for every model invocation, written **before** the outbound
  call, so an *attempted* call is not treated as free even if the node that
  made it raises and LangGraph discards its state update;
- a **settlement** for every invocation once its outcome is known (success,
  failure, cancellation, invalid end clock), carrying only allow-listed numeric
  and constant scalars.

The ledger is dependency-free (Python standard-library ``sqlite3`` only) and is
never a vector for content leakage: no prompt, response body, exception message,
URL, query string, username or secret is ever stored — only the documented
columns below.

Design rules (authoritative, see ``docs/architecture/adr/009-durable-run-usage-ledger.md``):

- **Run identity is a real execution identity, not a reproducible evidence id.**
  The gate/evidence ``run_id`` (``build_gate_run_id``) must stay reproducible for
  the manifest; the *execution* ``run_id`` here is minted per execution so a fresh
  run, its resume, and a different finished run with the same ticker+date are
  three distinct spend scopes. A fresh run never inherits a prior finished run's
  spend; a resume keeps its own.
- **Reservation and settlement are distinct.** A reservation stores the
  conservative estimate; a settlement stores the observed outcome. An invocation
  whose reservation is never settled (e.g. a crash between the provider returning
  and the node state update) is **unresolved possible spend** — it is never
  silently reset to zero and never treated as free on retry.
- **Provenance is honest per field.** A token/time value is ``provider`` /
  ``measured`` only when actually observed; an estimate stays ``estimated``; an
  unknown failed/in-flight cost is ``unavailable`` (never ``0``, never a
  fabricated provider count).
- **Fail closed.** A corrupt database, an unknown ``schema_version``, or a run row
  missing its identity raises :class:`LedgerError`; the caller must not treat the
  accounting as empty.
- **Thread safe.** Each write is a single SQLite transaction guarded by a process
  lock, so concurrent invocations cannot collide or lose an event.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Versioned ledger contract. A ledger written under a different schema/policy
# version is rejected rather than silently merged (fail closed).
LEDGER_SCHEMA_VERSION = "1.0"

# Reservation / event lifecycle states.
STATE_IN_FLIGHT = "in_flight"
STATE_SETTLED = "settled"

# Settlement statuses (the outcome of one logical invocation).
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INVALID_CLOCK = "invalid_clock"

_ALLOWED_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELLED, STATUS_INVALID_CLOCK}
)

# Per-field provenance labels (kept aligned with ``debate.budget`` constant names
# without importing them, so this low-level module has no upward dependency).
SOURCE_PROVIDER = "provider"
SOURCE_MEASURED = "measured"
SOURCE_ESTIMATED = "estimated"
SOURCE_UNAVAILABLE = "unavailable"
SOURCE_MISSING = "missing"

_ALLOWED_TOKEN_SOURCES = frozenset(
    {SOURCE_PROVIDER, SOURCE_ESTIMATED, SOURCE_UNAVAILABLE, SOURCE_MISSING}
)
_ALLOWED_SECONDS_SOURCES = frozenset(
    {SOURCE_MEASURED, SOURCE_ESTIMATED, SOURCE_UNAVAILABLE, SOURCE_MISSING}
)

# The phase labels a reservation/event may carry. Anything else is a constant
# ``unknown_phase`` so a free-form (possibly secret-bearing) string is never
# persisted.
PHASE_ANALYST = "analyst"
PHASE_STRUCTURED_FALLBACK = "structured_fallback"
PHASE_DEBATE = "debate"
PHASE_RESEARCH_MANAGER = "research_manager"
PHASE_TRADER = "trader"
PHASE_RISK = "risk"
PHASE_PORTFOLIO = "portfolio"
PHASE_UNKNOWN = "unknown_phase"

_ALLOWED_PHASES = frozenset(
    {
        PHASE_ANALYST,
        PHASE_STRUCTURED_FALLBACK,
        PHASE_DEBATE,
        PHASE_RESEARCH_MANAGER,
        PHASE_TRADER,
        PHASE_RISK,
        PHASE_PORTFOLIO,
        PHASE_UNKNOWN,
    }
)

_DB_FILENAME = "usage_ledger.db"


class LedgerError(RuntimeError):
    """Raised when the durable ledger is corrupt, mis-versioned or incomplete.

    Fail closed: a caller must treat an unreadable ledger as *unresolved*
    accounting, never as zero spend.
    """


def sanitize_phase(phase: Any) -> str:
    """Coerce a phase label to the allow-list (never store arbitrary text)."""
    value = str(phase or "")
    return value if value in _ALLOWED_PHASES else PHASE_UNKNOWN


def _sanitize_status(status: Any) -> str:
    value = str(status or "")
    if value not in _ALLOWED_STATUSES:
        raise LedgerError(f"invalid settlement status: {value!r}")
    return value


def _clean_token(value: Any) -> int | None:
    """A non-negative integral finite token count, or ``None`` (never fabricate)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN/inf
        return None
    if value < 0 or value != int(value):
        return None
    return int(value)


def _clean_seconds(value: Any) -> float | None:
    """A non-negative finite seconds value, or ``None`` (never fabricate)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if number < 0:
        return None
    return number


def _clean_source(value: Any, allowed: frozenset[str], fallback: str) -> str:
    text = str(value or "")
    return text if text in allowed else fallback


# Allow-listed per-side provenance labels. ``provider`` means the provider
# reported that side; ``estimated`` means it was filled by the character
# estimate; ``unavailable`` means it was not obtained. A filled estimate is NEVER
# stored as provider.
_SIDE_SOURCE_ALLOWED = frozenset({SOURCE_PROVIDER, SOURCE_ESTIMATED, SOURCE_UNAVAILABLE})


def _clean_side_source(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text in _SIDE_SOURCE_ALLOWED else None


def _decode_originals(value: Any) -> list[dict[str, Any]]:
    """Decode a persisted conflict-originals JSON column (safe; [] if bad)."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return _clean_conflict_originals(parsed)


def _clean_conflict_originals(value: Any) -> list[dict[str, Any]]:
    """Sanitize safe provider conflict originals to allow-listed scalar fields.

    Each original is a source-labelled block (``source`` / ``input_tokens`` /
    ``output_tokens`` / ``total_tokens`` / optional ``call_index``). Only those
    keys are kept and only integral/finite non-negative numbers; anything else is
    dropped (never raw text).
    """
    if not isinstance(value, (list, tuple)):
        return []
    cleaned: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        record: dict[str, Any] = {}
        source = entry.get("source")
        if isinstance(source, str) and source:
            record["source"] = source
        for key in ("input_tokens", "output_tokens", "total_tokens", "call_index"):
            number = _clean_token(entry.get(key))
            if number is not None:
                record[key] = number
        if record:
            cleaned.append(record)
    return cleaned


@dataclass(frozen=True)
class Reservation:
    """A durable pre-call reservation (estimated possible spend for an attempt)."""

    run_id: str
    invocation_id: str
    phase: str
    speaker: str
    reserved_tokens: int
    reserved_seconds: float
    state: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "phase": self.phase,
            "speaker": self.speaker,
            "reserved_tokens": self.reserved_tokens,
            "reserved_seconds": self.reserved_seconds,
            "state": self.state,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class UsageEvent:
    """A durable settled invocation outcome (allow-listed scalars only)."""

    run_id: str
    invocation_id: str
    phase: str
    speaker: str
    status: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    tokens_source: str
    seconds: float | None
    seconds_source: str
    token_source_partial: bool
    provider_conflict: bool
    transport_attempts: int | None
    unresolved: bool
    created_at: str
    # Per-side provenance: "provider" / "estimated" / "unavailable" / None. A
    # filled estimate is NEVER labelled provider. Kept separate from the aggregate
    # ``tokens_source`` so a partial split is attributed honestly per side.
    input_tokens_source: str | None = None
    output_tokens_source: str | None = None
    # Safe provider conflict originals (both blocks + per-call index), JSON-safe.
    conflict_originals: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "phase": self.phase,
            "speaker": self.speaker,
            "status": self.status,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "tokens_source": self.tokens_source,
            "seconds": self.seconds,
            "seconds_source": self.seconds_source,
            "token_source_partial": self.token_source_partial,
            "provider_conflict": self.provider_conflict,
            "transport_attempts": self.transport_attempts,
            "unresolved": self.unresolved,
            "input_tokens_source": self.input_tokens_source,
            "output_tokens_source": self.output_tokens_source,
            "conflict_originals": list(self.conflict_originals),
            "created_at": self.created_at,
        }


@dataclass
class RunSpend:
    """The reconciled spend for one execution derived entirely from the ledger.

    ``events`` are settled invocations (each counted once). ``unresolved`` are
    reservations left ``in_flight`` (possible spend with an unknown outcome).
    Re-deriving a resumed run from the same rows yields identical totals, so
    reconciliation is idempotent (never double-adds cumulative totals).
    """

    run_id: str
    events: list[UsageEvent] = field(default_factory=list)
    unresolved: list[Reservation] = field(default_factory=list)

    def has_unresolved(self) -> bool:
        """True when any attempt's cost/outcome is unresolved (fail-closed)."""
        return bool(self.unresolved) or any(ev.unresolved for ev in self.events)

    def unknown_cost_events(self) -> list[UsageEvent]:
        """Settled events whose outcome is unresolved or whose token cost is unknown.

        A failed/invalid-clock event is settled *with an unknown cost* (never
        ``0``-known); it stays here so the pre-call guard fails closed rather than
        admitting the next optional call as if the unknown spend were free.
        """
        result: list[UsageEvent] = []
        for ev in self.events:
            if ev.unresolved:
                result.append(ev)
                continue
            has_known_tokens = isinstance(ev.total_tokens, int) and ev.tokens_source in (
                SOURCE_PROVIDER,
                SOURCE_ESTIMATED,
            )
            if not has_known_tokens:
                result.append(ev)
        return result

    def known_token_events(self) -> list[UsageEvent]:
        """Settled events with a known token cost (partial sums are preserved)."""
        unknown = {id(ev) for ev in self.unknown_cost_events()}
        return [ev for ev in self.events if id(ev) not in unknown]

    def settled_tokens(self) -> int:
        """Sum of KNOWN token costs only (unknown events are excluded, never zeroed)."""
        return sum(
            int(ev.total_tokens)
            for ev in self.known_token_events()
        )

    def settled_seconds(self) -> float:
        """Sum of KNOWN measured/estimated seconds only."""
        return sum(
            float(ev.seconds)
            for ev in self.events
            if ev.seconds is not None
        )

    def unresolved_estimated_reserved_tokens(self) -> int:
        """Sum of the ESTIMATED reservations for unsettled attempts.

        This is a deterministic estimate, NOT a physical billing bound/upper bound
        on provider spend; it exists only so an unsettled attempt is not treated
        as free.
        """
        return sum(r.reserved_tokens for r in self.unresolved)


class UsageLedger:
    """A durable, run-scoped SQLite ledger of model-invocation spend.

    One ledger file may hold several executions (distinct ``run_id`` values). All
    methods are safe to call from multiple threads; writes are serialized by a
    process lock and each write is one transaction.
    """

    def __init__(self, path: str | Path, *, strict_existing: bool = False) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()
        self._strict_existing = bool(strict_existing)
        if self._strict_existing:
            # Strict resume: NEVER create a replacement DB / tables / metadata.
            # Validate the existing DB schema read-only and fail closed otherwise.
            self._validate_existing_readonly()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    # -- schema ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _validate_existing_readonly(self) -> None:
        """Validate an existing ledger's schema read-only (strict resume path).

        Opens the existing file with ``mode=ro`` so no CREATE/INSERT is performed,
        and requires the full schema (``ledger_meta`` with the expected
        ``schema_version``, ``runs``/``reservations``/``usage_events`` tables) to
        be present. A missing file / blank / wrong DB raises :class:`LedgerError`;
        the caller must NOT initialize a replacement and reset spend.
        """
        if not self.path.exists():
            raise LedgerError(
                f"usage ledger file {self.path.name!r} is missing on resume; "
                "refusing to initialize a replacement ledger (spend would reset to zero)"
            )
        try:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30.0)
        except sqlite3.DatabaseError as exc:
            raise LedgerError(f"usage ledger unreadable on resume: {type(exc).__name__}") from exc
        try:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            required = {"ledger_meta", "runs", "reservations", "usage_events"}
            missing = required - tables
            if missing:
                raise LedgerError(
                    "usage ledger on resume is missing table(s): "
                    + ", ".join(sorted(missing))
                )
            meta = conn.execute(
                "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
            ).fetchone()
            if meta is None or str(meta[0]) != LEDGER_SCHEMA_VERSION:
                raise LedgerError(
                    "usage ledger schema_version missing/unknown on resume"
                )
        except sqlite3.DatabaseError as exc:
            raise LedgerError(f"usage ledger unreadable on resume: {type(exc).__name__}") from exc
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ledger_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        schema_version TEXT NOT NULL,
                        policy_signature TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reservations (
                        run_id TEXT NOT NULL,
                        invocation_id TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        speaker TEXT NOT NULL,
                        reserved_tokens INTEGER NOT NULL,
                        reserved_seconds REAL NOT NULL,
                        state TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (run_id, invocation_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS usage_events (
                        run_id TEXT NOT NULL,
                        invocation_id TEXT NOT NULL,
                        phase TEXT NOT NULL,
                        speaker TEXT NOT NULL,
                        status TEXT NOT NULL,
                        input_tokens INTEGER,
                        output_tokens INTEGER,
                        total_tokens INTEGER,
                        tokens_source TEXT NOT NULL,
                        seconds REAL,
                        seconds_source TEXT NOT NULL,
                        token_source_partial INTEGER NOT NULL,
                        provider_conflict INTEGER NOT NULL,
                        transport_attempts INTEGER,
                        unresolved INTEGER NOT NULL,
                        input_tokens_source TEXT,
                        output_tokens_source TEXT,
                        conflict_originals TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (run_id, invocation_id)
                    )
                    """
                )
                conn.commit()
                # Confirm the on-disk schema version is compatible.
                row = conn.execute(
                    "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO ledger_meta(key, value) VALUES ('schema_version', ?)",
                        (LEDGER_SCHEMA_VERSION,),
                    )
                    conn.commit()
                elif str(row[0]) != LEDGER_SCHEMA_VERSION:
                    raise LedgerError(
                        "usage ledger schema_version mismatch: "
                        f"found {row[0]!r}, expected {LEDGER_SCHEMA_VERSION!r}"
                    )
            finally:
                conn.close()

    # -- run identity ---------------------------------------------------

    def begin_run(
        self,
        run_id: str,
        *,
        policy_signature: str = "",
        created_at: str = "",
        require_existing: bool = False,
    ) -> None:
        """Register a run identity (idempotent; compatible version required).

        Re-registering the same ``run_id`` (e.g. on a resume) is a no-op that only
        validates the schema version. A re-register under an incompatible policy
        signature raises :class:`LedgerError` (the checkpoint/ledger pair cannot
        be trusted).

        ``require_existing`` is set on a RESUME: the run row MUST already exist (a
        resumed checkpoint must never mint/register a fresh run under an existing
        checkpoint identity). A missing run row then raises :class:`LedgerError`
        instead of inserting one, so a checkpoint whose ledger row vanished fails
        closed rather than silently starting a new spend scope.
        """
        if not run_id:
            raise LedgerError("run_id is required to begin a ledger run")
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT schema_version, policy_signature FROM runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if row is None:
                    if require_existing:
                        raise LedgerError(
                            f"run {run_id!r} is absent from the ledger on resume; "
                            "refusing to register a new run under an existing checkpoint"
                        )
                    conn.execute(
                        "INSERT INTO runs(run_id, schema_version, policy_signature, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (run_id, LEDGER_SCHEMA_VERSION, str(policy_signature or ""), created_at),
                    )
                    conn.commit()
                    return
                if str(row[0]) != LEDGER_SCHEMA_VERSION:
                    raise LedgerError(
                        f"run {run_id!r} was written under schema_version {row[0]!r}"
                    )
                prior_policy = str(row[1] or "")
                if prior_policy and policy_signature and prior_policy != policy_signature:
                    raise LedgerError(
                        f"run {run_id!r} policy signature changed; refusing to merge"
                    )
            finally:
                conn.close()

    def has_run(self, run_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    # -- reservation / settlement --------------------------------------

    def reserve(
        self,
        *,
        run_id: str,
        invocation_id: str,
        phase: str,
        speaker: str,
        reserved_tokens: int,
        reserved_seconds: float,
        created_at: str = "",
    ) -> None:
        """Durably reserve possible spend for one attempted invocation.

        Written BEFORE the outbound call. Idempotent by ``(run_id,
        invocation_id)`` (a repeated reserve never resets an existing
        reservation). Requires the run to have been begun; a missing run row is a
        fail-closed :class:`LedgerError`.
        """
        if not run_id or not invocation_id:
            raise LedgerError("run_id and invocation_id are required to reserve")
        safe_phase = sanitize_phase(phase)
        tokens = _clean_token(reserved_tokens) or 0
        seconds = _clean_seconds(reserved_seconds) or 0.0
        with self._lock:
            conn = self._connect()
            try:
                run_row = conn.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if run_row is None:
                    raise LedgerError(
                        f"cannot reserve for unknown run {run_id!r} (missing identity)"
                    )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO reservations(
                        run_id, invocation_id, phase, speaker,
                        reserved_tokens, reserved_seconds, state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        invocation_id,
                        safe_phase,
                        str(speaker or ""),
                        int(tokens),
                        float(seconds),
                        STATE_IN_FLIGHT,
                        created_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def _scope_usage_in_txn(self, conn: sqlite3.Connection, run_id: str, phases: tuple[str, ...]) -> dict[str, Any]:
        """Build the budget-scoped usage dict for ``phases`` from rows in the OPEN
        transaction (so admission re-reads the CURRENT committed state, not a stale
        Python snapshot). Returns the same shape as
        ``budget.derive_debate_usage_from_events`` plus unresolved reservations.
        """
        from tradingagents.debate.budget import derive_debate_usage_from_events

        placeholders = ",".join("?" for _ in phases)
        event_rows = conn.execute(
            "SELECT run_id, invocation_id, phase, speaker, status, "
            "input_tokens, output_tokens, total_tokens, tokens_source, "
            "seconds, seconds_source, token_source_partial, "
            "provider_conflict, transport_attempts, unresolved, created_at, "
            "input_tokens_source, output_tokens_source, conflict_originals "
            f"FROM usage_events WHERE run_id = ? AND phase IN ({placeholders}) "
            "ORDER BY created_at, invocation_id",
            (run_id, *phases),
        ).fetchall()
        events = [self._row_to_event(row) for row in event_rows]
        reservation_rows = conn.execute(
            "SELECT invocation_id, phase, speaker, reserved_tokens, "
            "reserved_seconds, state, created_at FROM reservations "
            f"WHERE run_id = ? AND state = ? AND phase IN ({placeholders}) "
            "ORDER BY created_at, invocation_id",
            (run_id, STATE_IN_FLIGHT, *phases),
        ).fetchall()
        unresolved = [
            Reservation(
                run_id=run_id,
                invocation_id=str(row[0]),
                phase=str(row[1]),
                speaker=str(row[2]),
                reserved_tokens=int(row[3]),
                reserved_seconds=float(row[4]),
                state=str(row[5]),
                created_at=str(row[6]),
            )
            for row in reservation_rows
        ]
        return derive_debate_usage_from_events(events, unresolved=unresolved, phases=phases)

    def admit_debate_call(
        self,
        *,
        run_id: str,
        invocation_id: str,
        max_calls: int,
        reserved_tokens: int,
        reserved_seconds: float,
        speaker: str = "debate",
        created_at: str = "",
        config: Any = None,
    ) -> bool:
        """Atomically admit + reserve one debate call under the FULL budget policy.

        Runs a single ``BEGIN IMMEDIATE`` write transaction that RE-READS the run's
        current debate usage (settled events + ``in_flight`` reservations) and
        evaluates the whole budget policy — call limit, token/time capacity, summary
        reserve, and unresolved possible spend — INSIDE the transaction, then
        inserts the reservation only if admitted. Because SQLite serializes ``BEGIN
        IMMEDIATE`` writers across connections AND processes, two independent
        capture/ledger instances on the SAME run cannot both pass a stale preflight
        and then both reserve: the second re-reads the first's committed result.

        When ``config`` is supplied (the validated ``DebateTerminationConfig``) the
        full :func:`can_afford_optional_call` check runs inside the transaction; the
        reservation uses the config's ``next_call_estimate``. When ``config`` is
        ``None`` only the call count is enforced (backward-compatible call-limit
        check). A missing run row is a fail-closed :class:`LedgerError`.
        """
        return self._admit_in_txn(
            run_id=run_id,
            invocation_id=invocation_id,
            phases=("debate",),
            phase_label="debate",
            speaker=speaker,
            reserved_tokens=reserved_tokens,
            reserved_seconds=reserved_seconds,
            created_at=created_at,
            config=config,
            summary=False,
            max_calls=max_calls,
        )

    def admit_summary_call(
        self,
        *,
        run_id: str,
        invocation_id: str,
        max_calls: int,
        reserved_tokens: int,
        reserved_seconds: float,
        speaker: str = "Research Manager",
        created_at: str = "",
        config: Any = None,
    ) -> bool:
        """Atomically admit + reserve ONE summary attempt under the FULL policy.

        Like :meth:`admit_debate_call` but the scoped usage is debate +
        research_manager (the summary's own logical call), the reservation is
        written under the ``research_manager`` phase, and — when ``config`` is given
        — the whole :func:`can_afford_summary` check (call slot + token/time
        capacity + summary reserve + unresolved spend) runs from the CURRENT rows
        inside the same ``BEGIN IMMEDIATE`` transaction. Two independent
        capture/ledger instances on the SAME run cannot both pass a stale snapshot.
        A zero ``max_calls`` (0) means no call cap. A missing run row fails closed.
        """
        return self._admit_in_txn(
            run_id=run_id,
            invocation_id=invocation_id,
            phases=("debate", "research_manager"),
            phase_label="research_manager",
            speaker=speaker,
            reserved_tokens=reserved_tokens,
            reserved_seconds=reserved_seconds,
            created_at=created_at,
            config=config,
            summary=True,
            max_calls=max_calls,
        )

    def _admit_in_txn(
        self,
        *,
        run_id: str,
        invocation_id: str,
        phases: tuple[str, ...],
        phase_label: str,
        speaker: str,
        reserved_tokens: int,
        reserved_seconds: float,
        created_at: str,
        config: Any,
        summary: bool,
        max_calls: int,
    ) -> bool:
        """Shared atomic admission: re-read scope usage, re-run the budget check,
        then reserve — all inside ONE ``BEGIN IMMEDIATE`` transaction."""
        if not run_id or not invocation_id:
            raise LedgerError("run_id and invocation_id are required to admit")
        safe_phase = sanitize_phase(phase_label)
        try:
            with self._lock:
                conn = self._connect()
                try:
                    conn.isolation_level = None  # manual transaction control
                    conn.execute("BEGIN IMMEDIATE")
                    run_row = conn.execute(
                        "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
                    ).fetchone()
                    if run_row is None:
                        conn.execute("ROLLBACK")
                        raise LedgerError(
                            f"cannot admit for unknown run {run_id!r} (missing identity)"
                        )
                    # Re-read the CURRENT scoped usage from rows inside the txn.
                    scope_usage = self._scope_usage_in_txn(conn, run_id, phases)
                    if config is not None:
                        # Full policy evaluated against the fresh snapshot.
                        from tradingagents.debate.budget import (
                            can_afford_optional_call,
                            can_afford_summary,
                            next_call_estimate,
                        )

                        if summary:
                            affordable = can_afford_summary(scope_usage, config)
                        else:
                            affordable = can_afford_optional_call(scope_usage, config)
                        if not affordable:
                            conn.execute("ROLLBACK")
                            return False
                        est_tokens, est_seconds = next_call_estimate(config)
                        tokens = int(est_tokens)
                        seconds = float(est_seconds)
                    else:
                        # Call-count-only fallback (legacy callers).
                        existing = conn.execute(
                            "SELECT COUNT(*) FROM reservations "
                            f"WHERE run_id = ? AND phase IN ({','.join('?' for _ in phases)})",
                            (run_id, *phases),
                        ).fetchone()[0]
                        settled = conn.execute(
                            "SELECT COUNT(*) FROM usage_events "
                            f"WHERE run_id = ? AND phase IN ({','.join('?' for _ in phases)})",
                            (run_id, *phases),
                        ).fetchone()[0]
                        if int(max_calls) > 0 and max(int(existing), int(settled)) >= int(max_calls):
                            conn.execute("ROLLBACK")
                            return False
                        tokens = _clean_token(reserved_tokens) or 0
                        seconds = _clean_seconds(reserved_seconds) or 0.0
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO reservations(
                            run_id, invocation_id, phase, speaker,
                            reserved_tokens, reserved_seconds, state, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            invocation_id,
                            safe_phase,
                            str(speaker or ""),
                            int(tokens),
                            float(seconds),
                            STATE_IN_FLIGHT,
                            created_at,
                        ),
                    )
                    conn.execute("COMMIT")
                    return True
                finally:
                    conn.close()
        except sqlite3.DatabaseError as exc:
            raise LedgerError(f"usage ledger admit failed: {type(exc).__name__}") from exc

    def settle(
        self,
        *,
        run_id: str,
        invocation_id: str,
        status: str,
        phase: str = "",
        speaker: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        tokens_source: str = SOURCE_UNAVAILABLE,
        seconds: float | None = None,
        seconds_source: str = SOURCE_UNAVAILABLE,
        token_source_partial: bool = False,
        provider_conflict: bool = False,
        transport_attempts: int | None = None,
        unresolved: bool = False,
        created_at: str = "",
        input_tokens_source: str | None = None,
        output_tokens_source: str | None = None,
        conflict_originals: list[dict[str, Any]] | None = None,
    ) -> UsageEvent:
        """Durably record the observed outcome of one invocation (idempotent).

        Idempotent by ``(run_id, invocation_id)``: a repeated settle returns the
        already-recorded event and never adds a second row (so a replayed resume
        cannot double-count). Only allow-listed scalars are stored.
        """
        if not run_id or not invocation_id:
            raise LedgerError("run_id and invocation_id are required to settle")
        safe_status = _sanitize_status(status)
        safe_phase = sanitize_phase(phase)
        clean_in = _clean_token(input_tokens)
        clean_out = _clean_token(output_tokens)
        clean_total = _clean_token(total_tokens)
        clean_secs = _clean_seconds(seconds)
        safe_tok_source = _clean_source(tokens_source, _ALLOWED_TOKEN_SOURCES, SOURCE_UNAVAILABLE)
        safe_sec_source = _clean_source(
            seconds_source, _ALLOWED_SECONDS_SOURCES, SOURCE_UNAVAILABLE
        )
        clean_transport = _clean_token(transport_attempts)
        safe_in_source = _clean_side_source(input_tokens_source)
        safe_out_source = _clean_side_source(output_tokens_source)
        safe_originals = _clean_conflict_originals(conflict_originals)
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT * FROM usage_events WHERE run_id = ? AND invocation_id = ?",
                    (run_id, invocation_id),
                ).fetchone()
                if existing is not None:
                    # Idempotent: return the recorded event, do not double-add.
                    conn.execute(
                        "UPDATE reservations SET state = ? "
                        "WHERE run_id = ? AND invocation_id = ?",
                        (STATE_SETTLED, run_id, invocation_id),
                    )
                    conn.commit()
                    return self._row_to_event(existing)
                run_row = conn.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if run_row is None:
                    raise LedgerError(
                        f"cannot settle for unknown run {run_id!r} (missing identity)"
                    )
                conn.execute(
                    """
                    INSERT INTO usage_events(
                        run_id, invocation_id, phase, speaker, status,
                        input_tokens, output_tokens, total_tokens, tokens_source,
                        seconds, seconds_source, token_source_partial,
                        provider_conflict, transport_attempts, unresolved,
                        input_tokens_source, output_tokens_source,
                        conflict_originals, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        invocation_id,
                        safe_phase,
                        str(speaker or ""),
                        safe_status,
                        clean_in,
                        clean_out,
                        clean_total,
                        safe_tok_source,
                        clean_secs,
                        safe_sec_source,
                        1 if token_source_partial else 0,
                        1 if provider_conflict else 0,
                        clean_transport,
                        1 if unresolved else 0,
                        safe_in_source,
                        safe_out_source,
                        json.dumps(safe_originals, sort_keys=True) if safe_originals else None,
                        created_at,
                    ),
                )
                conn.execute(
                    "UPDATE reservations SET state = ? "
                    "WHERE run_id = ? AND invocation_id = ?",
                    (STATE_SETTLED, run_id, invocation_id),
                )
                conn.commit()
                return UsageEvent(
                    run_id=run_id,
                    invocation_id=invocation_id,
                    phase=safe_phase,
                    speaker=str(speaker or ""),
                    status=safe_status,
                    input_tokens=clean_in,
                    output_tokens=clean_out,
                    total_tokens=clean_total,
                    tokens_source=safe_tok_source,
                    seconds=clean_secs,
                    seconds_source=safe_sec_source,
                    token_source_partial=bool(token_source_partial),
                    provider_conflict=bool(provider_conflict),
                    transport_attempts=clean_transport,
                    unresolved=bool(unresolved),
                    created_at=created_at,
                    input_tokens_source=safe_in_source,
                    output_tokens_source=safe_out_source,
                    conflict_originals=safe_originals,
                )
            except sqlite3.DatabaseError as exc:
                raise LedgerError(f"usage ledger write failed: {type(exc).__name__}") from exc
            finally:
                conn.close()

    # -- read / reconcile ----------------------------------------------

    @staticmethod
    def _row_to_event(row: Any) -> UsageEvent:
        # Columns: run_id, invocation_id, phase, speaker, status, input_tokens,
        # output_tokens, total_tokens, tokens_source, seconds, seconds_source,
        # token_source_partial, provider_conflict, transport_attempts, unresolved,
        # created_at
        return UsageEvent(
            run_id=str(row[0]),
            invocation_id=str(row[1]),
            phase=str(row[2]),
            speaker=str(row[3]),
            status=str(row[4]),
            input_tokens=row[5],
            output_tokens=row[6],
            total_tokens=row[7],
            tokens_source=str(row[8]),
            seconds=row[9],
            seconds_source=str(row[10]),
            token_source_partial=bool(row[11]),
            provider_conflict=bool(row[12]),
            transport_attempts=row[13],
            unresolved=bool(row[14]),
            created_at=str(row[15]),
            input_tokens_source=row[16],
            output_tokens_source=row[17],
            conflict_originals=_decode_originals(row[18]),
        )

    def read_run_spend(self, run_id: str, *, strict: bool = True) -> RunSpend:
        """Reconcile one execution's spend from the ledger (idempotent).

        Returns settled events (each exactly once, ordered by ``created_at`` then
        ``invocation_id`` for determinism) plus reservations still ``in_flight``
        (unresolved possible spend). A corrupt database raises
        :class:`LedgerError`.

        **Strict mode (the resume path).** When ``strict`` is true, a missing run
        row / missing ledger file / unreadable schema raises :class:`LedgerError`.
        A resume MUST open the existing ledger/run strictly: if the ledger file was
        deleted or lost its schema/run row, this call fails closed so the caller
        does NOT initialize a replacement ledger and silently reset spend to zero.
        A genuinely fresh run uses a *new* ``run_id`` and calls :meth:`begin_run`
        first, so it never reads an unknown run.
        """
        if strict and not self.path.exists():
            raise LedgerError(
                f"usage ledger file is missing for resume of run {run_id!r}"
            )
        try:
            with self._lock:
                conn = self._connect()
                try:
                    if strict:
                        meta = conn.execute(
                            "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
                        ).fetchone()
                        if meta is None or str(meta[0]) != LEDGER_SCHEMA_VERSION:
                            raise LedgerError(
                                "usage ledger schema missing/unknown on resume"
                            )
                        run_row = conn.execute(
                            "SELECT schema_version FROM runs WHERE run_id = ?", (run_id,)
                        ).fetchone()
                        if run_row is None:
                            raise LedgerError(
                                f"run {run_id!r} is absent from the ledger on resume; "
                                "refusing to reinitialize and reset spend"
                            )
                        if str(run_row[0]) != LEDGER_SCHEMA_VERSION:
                            raise LedgerError(
                                f"run {run_id!r} ledger schema_version mismatch on resume"
                            )
                    event_rows = conn.execute(
                        "SELECT run_id, invocation_id, phase, speaker, status, "
                        "input_tokens, output_tokens, total_tokens, tokens_source, "
                        "seconds, seconds_source, token_source_partial, "
                        "provider_conflict, transport_attempts, unresolved, created_at, "
                        "input_tokens_source, output_tokens_source, conflict_originals "
                        "FROM usage_events WHERE run_id = ? "
                        "ORDER BY created_at, invocation_id",
                        (run_id,),
                    ).fetchall()
                    reservation_rows = conn.execute(
                        "SELECT invocation_id, phase, speaker, reserved_tokens, "
                        "reserved_seconds, state, created_at FROM reservations "
                        "WHERE run_id = ? AND state = ? ORDER BY created_at, invocation_id",
                        (run_id, STATE_IN_FLIGHT),
                    ).fetchall()
                finally:
                    conn.close()
        except sqlite3.DatabaseError as exc:
            raise LedgerError(f"usage ledger unreadable: {type(exc).__name__}") from exc

        events = [self._row_to_event(row) for row in event_rows]
        unresolved = [
            Reservation(
                run_id=run_id,
                invocation_id=str(row[0]),
                phase=str(row[1]),
                speaker=str(row[2]),
                reserved_tokens=int(row[3]),
                reserved_seconds=float(row[4]),
                state=str(row[5]),
                created_at=str(row[6]),
            )
            for row in reservation_rows
        ]
        return RunSpend(run_id=run_id, events=events, unresolved=unresolved)


# -- run identity helpers ------------------------------------------------


def open_ledger_fresh(path: str | Path) -> UsageLedger:
    """Open (creating if absent) a ledger for a FRESH execution."""
    return UsageLedger(path)


def open_ledger_strict(path: str | Path) -> UsageLedger:
    """Open an EXISTING ledger for a RESUME, failing closed if it is absent.

    A resume must never initialize a replacement ledger: if the file is missing
    (deleted between the SQLite graph checkpoint and the resume), this raises
    :class:`LedgerError` so the caller keeps accounting unreadable and refuses
    further OPTIONAL calls rather than silently resetting spend to zero.
    """
    target = Path(path).expanduser()
    if not target.exists():
        raise LedgerError(
            f"usage ledger file {target.name!r} is missing on resume; refusing to "
            "initialize a replacement ledger (spend would reset to zero)"
        )
    return UsageLedger(target, strict_existing=True)


def new_run_id(ticker: str, trade_date: str, *, nonce: str | None = None) -> str:
    """Mint a real execution identity for a fresh run.

    The identity is intentionally **not** a reproducible gate/evidence id: a fresh
    run gets a new value even for the same ticker+date, so it never inherits a
    prior finished run's spend. ``nonce`` is injectable for deterministic tests;
    when omitted a UUID4 is used (run identity is not part of any reproducible
    artifact).
    """
    import uuid

    safe_ticker = "".join(ch for ch in str(ticker or "").upper() if ch.isalnum() or ch in "._-")
    token = nonce if nonce is not None else uuid.uuid4().hex
    return f"run:{safe_ticker}:{trade_date}:{token}"


def ledger_path_for_results_dir(results_dir: str | Path | None, ticker: str, trade_date: str) -> str | None:
    """The default per-run ledger path under ``results_dir`` (or ``None``).

    Kept deterministic on the ticker/date directory so a resume of the same
    execution finds the same ledger file; the *run identity* (not the path) is what
    distinguishes executions. Returns ``None`` when no results directory is
    configured so default offline runs never touch disk.
    """
    if not results_dir:
        return None
    safe_ticker = "".join(
        ch for ch in str(ticker or "").lower() if ch in "abcdefghijklmnopqrstuvwxyz0123456789._-"
    ).strip(".") or "unknown"
    safe_date = "".join(
        ch for ch in str(trade_date or "") if ch in "0123456789-"
    ) or "unknown"
    root = Path(str(results_dir)).expanduser() / safe_ticker / safe_date / "audit"
    return str(root / _DB_FILENAME)


def policy_signature(
    *,
    ledger_schema_version: str = LEDGER_SCHEMA_VERSION,
    debate_config: Any = None,
) -> str:
    """A stable signature of the accounting policy a run was written under.

    A checkpoint/ledger pair made under an incompatible signature is rejected so
    a policy change never silently merges two different accounting bases.
    """
    parts = [f"ledger_schema={ledger_schema_version}"]
    if debate_config is not None:
        for name in (
            "enabled",
            "max_calls",
            "max_tokens",
            "max_time",
            "reserved_summary_tokens",
            "reserved_summary_seconds",
            "next_round_estimate_tokens",
            "next_round_estimate_seconds",
        ):
            parts.append(f"{name}={getattr(debate_config, name, None)}")
    return json.dumps(parts, sort_keys=True)
