"""Append-only, hash-chained JSONL audit log."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from trading.clock import SystemClock
from trading.models import AuditEvent, AuditIntegrityError, DecisionValidationError, EventType

GENESIS_HASH = "0" * 64
_HASHED_FIELDS = ("event_id", "run_id", "timestamp", "event_type", "payload", "prev_hash")
_ALL_FIELDS = (*_HASHED_FIELDS, "entry_hash")
_HEAD_FIELDS = ("count", "last_hash", "last_event_id")


def _utc_now() -> datetime:
    return SystemClock().now()


def _uuid_hex() -> str:
    return uuid.uuid4().hex


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_bytes(value: Any) -> bytes:
    return _canonical_json(value).encode("utf-8")


def _normalise_key(key: Any) -> str:
    if isinstance(key, Enum):
        return str(key.value)
    return str(key)


def _normalise_payload(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DecisionValidationError("payload floats must be finite")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DecisionValidationError("payload datetimes must be timezone-aware")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _normalise_payload(value.value)
    if isinstance(value, Mapping):
        return {_normalise_key(k): _normalise_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise_payload(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalised = [_normalise_payload(item) for item in value]
        return sorted(normalised, key=lambda item: _canonical_json(item))
    if isinstance(value, Path):
        return str(value)
    raise DecisionValidationError(
        f"payload value is not JSON-serialisable: {type(value).__name__}"
    )


def _file_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_size, stat.st_mtime_ns, stat.st_ino)


class AuditLog:
    """An append-only audit log with a hash chain and a truncation anchor.

    The JSONL file is only ever opened with ``O_APPEND``. Each event hashes the
    previous event's hash, so edits or deletions in the middle of the chain are
    detectable. A small ``.head`` sidecar records the expected event count and
    tail hash, which makes deletion of the final entry detectable too. The
    sidecar is metadata; it is never part of the audit event stream.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _uuid_hex,
    ) -> None:
        self._path = Path(path)
        self._head_path = self._path.with_name(f"{self._path.name}.head")
        self._clock = clock
        self._id_factory = id_factory
        self._thread_lock = threading.RLock()
        self._last_hash = GENESIS_HASH
        self._count = 0
        self._signature: tuple[tuple[int, int, int] | None, tuple[int, int, int] | None] | None = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, self._locked_fd(
            os.O_WRONLY | os.O_CREAT | os.O_APPEND, fcntl.LOCK_EX
        ):
            self._load_and_verify_locked()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def head_path(self) -> Path:
        return self._head_path

    def append(
        self,
        *,
        run_id: str,
        event_type: EventType | str,
        payload: Mapping[str, Any],
    ) -> AuditEvent:
        if not isinstance(run_id, str) or not run_id.strip():
            raise DecisionValidationError("run_id must be a non-empty string")
        if not isinstance(payload, Mapping):
            raise DecisionValidationError("payload must be a mapping")
        event_kind = self._coerce_event_type(event_type)
        normalised_payload = _normalise_payload(dict(payload))
        if not isinstance(normalised_payload, dict):
            raise DecisionValidationError("payload must serialise to a JSON object")

        timestamp = self._clock()
        if not isinstance(timestamp, datetime):
            raise DecisionValidationError("clock must return a datetime")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise DecisionValidationError("clock must return a timezone-aware datetime")

        event_id = str(self._id_factory())
        if not event_id.strip():
            raise DecisionValidationError("event id must be non-empty")

        with self._thread_lock, self._locked_fd(
            os.O_WRONLY | os.O_CREAT | os.O_APPEND, fcntl.LOCK_EX
        ) as fd:
            self._ensure_verified_locked()
            core = {
                "event_id": event_id,
                "run_id": run_id,
                "timestamp": timestamp.isoformat(),
                "event_type": event_kind.value,
                "payload": normalised_payload,
                "prev_hash": self._last_hash,
            }
            entry_hash = self._hash_core(core)
            record = {**core, "entry_hash": entry_hash}
            line = (_canonical_json(record) + "\n").encode("utf-8")
            self._write_all(fd, line)
            os.fsync(fd)

            new_count = self._count + 1
            self._write_head(new_count, entry_hash, event_id)
            self._last_hash = entry_hash
            self._count = new_count
            self._signature = self._current_signature()

        return AuditEvent(
            event_id=event_id,
            run_id=run_id,
            timestamp=timestamp,
            event_type=event_kind,
            payload=normalised_payload,
            prev_hash=core["prev_hash"],
            entry_hash=entry_hash,
        )

    def read_all(self) -> tuple[AuditEvent, ...]:
        with self._thread_lock:
            if not self._path.exists():
                if self._head_path.exists():
                    raise AuditIntegrityError("audit head exists without an audit log")
                return ()
            with self._locked_fd(os.O_RDONLY, fcntl.LOCK_SH):
                return tuple(self._load_and_verify_locked())

    def verify_integrity(self) -> None:
        with self._thread_lock:
            if not self._path.exists():
                if self._head_path.exists():
                    raise AuditIntegrityError("audit head exists without an audit log")
                return
            with self._locked_fd(os.O_RDONLY, fcntl.LOCK_SH):
                self._load_and_verify_locked()

    @staticmethod
    def _coerce_event_type(event_type: EventType | str) -> EventType:
        if isinstance(event_type, EventType):
            return event_type
        try:
            return EventType(event_type)
        except (TypeError, ValueError) as exc:
            raise DecisionValidationError(f"unknown event type: {event_type!r}") from exc

    @staticmethod
    def _hash_core(core: Mapping[str, Any]) -> str:
        return hashlib.sha256(_canonical_bytes(dict(core))).hexdigest()

    @contextmanager
    def _locked_fd(self, flags: int, lock_kind: int) -> Iterator[int]:
        fd = os.open(self._path, flags, 0o600)
        try:
            fcntl.flock(fd, lock_kind)
            yield fd
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _current_signature(self) -> tuple[tuple[int, int, int] | None, tuple[int, int, int] | None]:
        return (_file_signature(self._path), _file_signature(self._head_path))

    def _ensure_verified_locked(self) -> None:
        if self._signature != self._current_signature():
            self._load_and_verify_locked()

    def _load_and_verify_locked(self) -> list[AuditEvent]:
        events = self._read_events_locked()
        expected_prev = GENESIS_HASH
        for line_number, record in enumerate(events, start=1):
            event = self._verify_record(record, line_number, expected_prev)
            expected_prev = event.entry_hash

        head = self._read_head()
        if head is None:
            if events:
                raise AuditIntegrityError("audit log is non-empty but the head anchor is missing")
        else:
            if head["count"] != len(events):
                raise AuditIntegrityError(
                    f"audit head count {head['count']} does not match {len(events)} entries"
                )
            if head["last_hash"] != expected_prev:
                raise AuditIntegrityError("audit head tail hash does not match the log")
            if events and head["last_event_id"] != events[-1]["event_id"]:
                raise AuditIntegrityError("audit head event id does not match the log")

        self._last_hash = expected_prev
        self._count = len(events)
        self._signature = self._current_signature()
        return [self._to_event(record) for record in events]

    def _read_events_locked(self) -> list[dict[str, Any]]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return []
        if raw and not raw.endswith(b"\n"):
            raise AuditIntegrityError("audit log ends with a partial line")
        records: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(raw.splitlines(), start=1):
            if not raw_line.strip():
                raise AuditIntegrityError(f"audit log line {line_number} is blank")
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AuditIntegrityError(
                    f"audit log line {line_number} is not valid JSON"
                ) from exc
            if not isinstance(record, dict):
                raise AuditIntegrityError(f"audit log line {line_number} is not an object")
            if set(record) != set(_ALL_FIELDS):
                raise AuditIntegrityError(
                    f"audit log line {line_number} has unexpected fields"
                )
            record["_raw"] = raw_line
            records.append(record)
        return records

    def _verify_record(
        self,
        record: Mapping[str, Any],
        line_number: int,
        expected_prev: str,
    ) -> AuditEvent:
        if record["prev_hash"] != expected_prev:
            raise AuditIntegrityError(
                f"audit log line {line_number} breaks the hash chain"
            )
        if not self._is_hash(record["prev_hash"]) or not self._is_hash(record["entry_hash"]):
            raise AuditIntegrityError(f"audit log line {line_number} has an invalid hash")
        core = {field: record[field] for field in _HASHED_FIELDS}
        computed = self._hash_core(core)
        if computed != record["entry_hash"]:
            raise AuditIntegrityError(
                f"audit log line {line_number} hash does not match its contents"
            )
        event = self._to_event(record)
        return event

    @staticmethod
    def _is_hash(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    def _to_event(self, record: Mapping[str, Any]) -> AuditEvent:
        try:
            timestamp = datetime.fromisoformat(record["timestamp"])
            event_type = EventType(record["event_type"])
        except (TypeError, ValueError) as exc:
            raise AuditIntegrityError("audit event metadata is invalid") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise AuditIntegrityError("audit event timestamp is timezone-naive")
        payload = record["payload"]
        if not isinstance(payload, dict):
            raise AuditIntegrityError("audit event payload is not an object")
        try:
            return AuditEvent(
                event_id=record["event_id"],
                run_id=record["run_id"],
                timestamp=timestamp,
                event_type=event_type,
                payload=payload,
                prev_hash=record["prev_hash"],
                entry_hash=record["entry_hash"],
            )
        except DecisionValidationError as exc:
            raise AuditIntegrityError("audit event fields are invalid") from exc

    def _read_head(self) -> dict[str, Any] | None:
        try:
            raw = self._head_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        if not raw.strip():
            raise AuditIntegrityError("audit head is empty")
        try:
            head = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuditIntegrityError("audit head is not valid JSON") from exc
        if not isinstance(head, dict) or set(head) != set(_HEAD_FIELDS):
            raise AuditIntegrityError("audit head has unexpected fields")
        if not isinstance(head["count"], int) or isinstance(head["count"], bool):
            raise AuditIntegrityError("audit head count is invalid")
        if head["count"] < 0:
            raise AuditIntegrityError("audit head count is negative")
        if not self._is_hash(head["last_hash"]):
            raise AuditIntegrityError("audit head hash is invalid")
        if not isinstance(head["last_event_id"], str):
            raise AuditIntegrityError("audit head event id is invalid")
        return head

    def _write_head(self, count: int, last_hash: str, last_event_id: str) -> None:
        head = {
            "count": count,
            "last_hash": last_hash,
            "last_event_id": last_event_id,
        }
        data = (_canonical_json(head) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(
            dir=self._head_path.parent,
            prefix=f".{self._head_path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._head_path)
            directory = os.open(self._head_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
            raise

    @staticmethod
    def _write_all(fd: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("could not append audit event")
            offset += written
