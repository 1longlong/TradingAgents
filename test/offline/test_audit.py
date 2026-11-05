"""Append-only audit log tests."""

from __future__ import annotations

import itertools
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading.audit import GENESIS_HASH, AuditLog
from trading.models import AuditIntegrityError, DecisionValidationError, EventType

FIXED_NOW = datetime(2024, 1, 5, 21, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return FIXED_NOW


def _ids():
    counter = itertools.count(1)
    return lambda: f"evt-{next(counter)}"


def _log(tmp_path: Path, *, clock=_clock, id_factory=None) -> AuditLog:
    return AuditLog(
        tmp_path / "audit.jsonl",
        clock=clock,
        id_factory=id_factory or _ids(),
    )


def _rewrite_entry(path: Path, index: int, mutate) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[index])
    mutate(record)
    lines[index] = json.dumps(record, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _touch(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


@pytest.mark.unit
def test_fr04_required_fields_and_genesis_hash(tmp_path):
    """[FR-04] Every entry carries run_id, timestamp, event_type, and payload."""
    log = _log(tmp_path)
    event = log.append(
        run_id="run-1",
        event_type=EventType.DECISION_RECEIVED,
        payload={"decision_id": "dec-1", "amount": Decimal("10.50")},
    )

    assert event.run_id == "run-1"
    assert event.timestamp == FIXED_NOW
    assert event.event_type is EventType.DECISION_RECEIVED
    assert event.payload == {"decision_id": "dec-1", "amount": "10.50"}
    assert event.prev_hash == GENESIS_HASH
    assert len(event.entry_hash) == 64
    assert log.path.read_text(encoding="utf-8").endswith("\n")
    assert log.head_path.exists()

    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].event_id == event.event_id
    assert entries[0].entry_hash == event.entry_hash


@pytest.mark.unit
def test_fr04_append_preserves_prior_bytes_and_links_hash_chain(tmp_path):
    """[FR-04] New entries append; existing bytes are never rewritten."""
    log = _log(tmp_path)
    first = log.append(
        run_id="run-1",
        event_type=EventType.DECISION_RECEIVED,
        payload={"n": 1},
    )
    before = log.path.read_bytes()

    second = log.append(
        run_id="run-1",
        event_type=EventType.RULE_EVALUATED,
        payload={"n": 2},
    )

    assert log.path.read_bytes().startswith(before)
    assert second.prev_hash == first.entry_hash
    assert [entry.payload["n"] for entry in log.read_all()] == [1, 2]


@pytest.mark.unit
def test_fr04_payload_normalises_decimals_datetimes_enums_and_sets(tmp_path):
    """[FR-04] Audit payloads are canonical JSON while preserving meaning."""
    log = _log(tmp_path)
    event = log.append(
        run_id="run-1",
        event_type=EventType.STATE_LOADED,
        payload={
            "decimal": Decimal("1.2300"),
            "when": FIXED_NOW,
            "kind": EventType.STATE_RESET,
            "items": (Decimal("2"), "x"),
            "symbols": frozenset({"b", "a"}),
            "path": Path("a/b"),
        },
    )

    assert event.payload["decimal"] == "1.2300"
    assert event.payload["when"] == FIXED_NOW.isoformat()
    assert event.payload["kind"] == "STATE_RESET"
    assert event.payload["items"] == ["2", "x"]
    assert event.payload["symbols"] == ["a", "b"]
    assert event.payload["path"] == "a/b"


@pytest.mark.unit
def test_fr04_reload_continues_the_existing_chain(tmp_path):
    """[FR-04] A fresh process resumes from the persisted tail hash."""
    path = tmp_path / "audit.jsonl"
    first = AuditLog(path, clock=_clock, id_factory=_ids()).append(
        run_id="run-1",
        event_type=EventType.DECISION_RECEIVED,
        payload={"n": 1},
    )

    reopened = AuditLog(path, clock=_clock, id_factory=_ids())
    second = reopened.append(
        run_id="run-1",
        event_type=EventType.ORDER_EXECUTED,
        payload={"n": 2},
    )

    assert second.prev_hash == first.entry_hash
    assert len(reopened.read_all()) == 2


@pytest.mark.unit
def test_fr04_string_event_type_is_accepted(tmp_path):
    """[FR-04] Event type strings are validated against the enum."""
    log = _log(tmp_path)
    event = log.append(
        run_id="run-1",
        event_type="STATE_LOADED",
        payload={},
    )
    assert event.event_type is EventType.STATE_LOADED


@pytest.mark.unit
def test_fr04_invalid_inputs_do_not_write_entries(tmp_path):
    """[FR-04] Invalid append calls fail before touching the audit stream."""
    log = _log(tmp_path)

    with pytest.raises(DecisionValidationError):
        log.append(run_id=" ", event_type=EventType.STATE_LOADED, payload={})
    with pytest.raises(DecisionValidationError):
        log.append(run_id="run-1", event_type="NOT_AN_EVENT", payload={})
    with pytest.raises(DecisionValidationError):
        log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload=[])
    with pytest.raises(DecisionValidationError):
        log.append(
            run_id="run-1",
            event_type=EventType.STATE_LOADED,
            payload={"bad": float("nan")},
        )

    assert log.read_all() == ()

    naive_clock = _log(
        tmp_path / "naive",
        clock=lambda: datetime(2024, 1, 5, 21, 0),
    )
    with pytest.raises(DecisionValidationError):
        naive_clock.append(
            run_id="run-1",
            event_type=EventType.STATE_LOADED,
            payload={},
        )
    assert naive_clock.read_all() == ()


@pytest.mark.unit
def test_fr04_empty_log_is_valid_and_has_no_head(tmp_path):
    """[FR-04] A fresh audit log verifies and reads as empty."""
    log = _log(tmp_path)
    assert log.read_all() == ()
    log.verify_integrity()
    assert not log.head_path.exists()


@pytest.mark.unit
def test_inv03_modification_of_existing_entry_detected(tmp_path):
    """[INV-03] Changing an existing entry breaks the hash chain."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    log.append(run_id="run-1", event_type=EventType.STATE_SAVED, payload={"n": 2})

    _rewrite_entry(
        log.path,
        0,
        lambda record: record["payload"].__setitem__("n", 999),
    )

    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()
    with pytest.raises(AuditIntegrityError):
        log.read_all()


@pytest.mark.unit
def test_inv03_append_after_tamper_fails(tmp_path):
    """[INV-03] Appending refuses to extend a modified log."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    _rewrite_entry(
        log.path,
        0,
        lambda record: record["payload"].__setitem__("n", 999),
    )
    _touch(log.path)

    with pytest.raises(AuditIntegrityError):
        log.append(run_id="run-1", event_type=EventType.STATE_SAVED, payload={"n": 2})


@pytest.mark.unit
def test_inv03_truncation_of_last_entry_detected(tmp_path):
    """[INV-03] The head anchor detects deletion of the final entry."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    log.append(run_id="run-1", event_type=EventType.STATE_SAVED, payload={"n": 2})

    lines = log.path.read_text(encoding="utf-8").splitlines(keepends=True)
    log.path.write_text("".join(lines[:-1]), encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()


@pytest.mark.unit
def test_inv03_truncation_to_empty_or_missing_file_detected(tmp_path):
    """[INV-03] Deleting all entries or the audit file is not a reset."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})

    log.path.write_text("", encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()

    log.path.unlink()
    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()


@pytest.mark.unit
def test_inv03_missing_head_anchor_detected(tmp_path):
    """[INV-03] A non-empty log without its anchor is treated as truncated."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    log.head_path.unlink()

    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()
    with pytest.raises(AuditIntegrityError):
        log.read_all()


@pytest.mark.unit
def test_inv03_head_tamper_detected_and_append_blocked(tmp_path):
    """[INV-03] A modified truncation anchor is rejected."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    head = json.loads(log.head_path.read_text(encoding="utf-8"))
    head["last_hash"] = "f" * 64
    log.head_path.write_text(json.dumps(head), encoding="utf-8")

    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()
    with pytest.raises(AuditIntegrityError):
        log.append(run_id="run-1", event_type=EventType.STATE_SAVED, payload={})


@pytest.mark.unit
def test_inv03_corrupt_json_and_extra_fields_detected(tmp_path):
    """[INV-03] Corrupt records and unexpected fields are integrity failures."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    log.path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(AuditIntegrityError):
        log.verify_integrity()

    log2 = _log(tmp_path / "extra")
    log2.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    _rewrite_entry(log2.path, 0, lambda record: record.__setitem__("extra", True))
    with pytest.raises(AuditIntegrityError):
        log2.verify_integrity()


@pytest.mark.unit
def test_inv03_events_are_frozen_and_no_mutation_api_exists(tmp_path):
    """[INV-03] Callers cannot mutate an entry or truncate the log."""
    log = _log(tmp_path)
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={"n": 1})
    event = log.read_all()[0]

    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"  # type: ignore[misc]

    for method in ("update", "delete", "truncate", "clear"):
        assert not hasattr(log, method)


@pytest.mark.unit
def test_fr04_concurrent_appends_are_serialised(tmp_path):
    """[FR-04] Concurrent writers cannot interleave or break the chain."""
    log = _log(tmp_path, id_factory=None)

    def worker(worker_id: int) -> None:
        for item in range(5):
            log.append(
                run_id=f"run-{worker_id}",
                event_type=EventType.RULE_EVALUATED,
                payload={"worker": worker_id, "item": item},
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))

    entries = log.read_all()
    assert len(entries) == 20
    log.verify_integrity()


@pytest.mark.unit
def test_fr04_parent_directory_is_created(tmp_path):
    """[FR-04] Audit storage can be initialised on a fresh run directory."""
    path = tmp_path / "nested" / "run" / "audit.jsonl"
    log = AuditLog(path, clock=_clock, id_factory=_ids())
    log.append(run_id="run-1", event_type=EventType.STATE_LOADED, payload={})
    assert path.exists()
