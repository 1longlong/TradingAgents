"""Sanitized, append-only failure audit for debate model invocations.

When a Bull/Bear ``llm.invoke`` raises, the researcher re-raises (the existing
abort behavior is preserved) and, before re-raising, appends ONE sanitized
record to a durable failure ledger. The ledger is a safety/audit channel, not a
state update and not a resume mechanism.

Binding safety contracts (see AGENTS.md; NFR-AUD-001 / INV-6):

- The record contains ONLY allow-listed fields: a constant error *class* /
  status / reason plus safe usage scalars. It NEVER contains the raw exception
  message, the prompt, the response body, or any authentication material — even
  in "redacted" form.
- Writing a ledger entry does **not** advance a failed LangGraph checkpoint. The
  local usage dict computed before the exception is not persisted by the
  framework, so this ledger is the only durable record of the failed attempt and
  cross-resume hard-budget accounting is **not** claimed fixed by it.
- No silent auto-resume or continue-after-failure is performed here.

The helper is dependency-light and JSON-safe. If no ``path`` is configured the
helper is a no-op (returns ``None``) so default/offline runs never touch disk.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tradingagents.debate.budget import SOURCE_UNAVAILABLE

# Allow-listed error classes. An unexpected exception type maps to UNKNOWN so
# the raw class name/message is never leaked into the ledger.
ERROR_CLASS_ABORTED = "invocation_aborted"
ERROR_CLASS_TIMEOUT = "invocation_timeout"
ERROR_CLASS_PROVIDER = "provider_error"
ERROR_CLASS_UNKNOWN = "unknown_error"

_ALLOWED_ERROR_CLASSES = frozenset(
    {
        ERROR_CLASS_ABORTED,
        ERROR_CLASS_TIMEOUT,
        ERROR_CLASS_PROVIDER,
        ERROR_CLASS_UNKNOWN,
    }
)

# Allow-listed safe usage scalars that may accompany a failed attempt. None of
# these carry content; a value is recorded only when it already exists. A failed
# attempt never fabricates tokens/time.
_SAFE_USAGE_KEYS = ("calls", "failed_calls", "transport_attempts", "turn_index")

# Constant status labels for a failure record (never free-form text).
STATUS_CLOCK_ABORT = "clock_abort_before_invoke"
STATUS_INVOKE_FAILED = "invoke_failed"
STATUS_CLOCK_END_INVALID = "clock_invalid_after_invoke"
STATUS_COMPLETED = "completed"


def classify_error(error: BaseException | None) -> str:
    """Map an exception to an allow-listed constant error class.

    Uses only the *type name* (never the message). Anything not recognised maps
    to ``unknown_error`` so arbitrary exception text is never recorded.
    """
    if error is None:
        return ERROR_CLASS_UNKNOWN
    name = type(error).__name__.lower()
    if "timeout" in name:
        return ERROR_CLASS_TIMEOUT
    if "abort" in name or "cancel" in name:
        return ERROR_CLASS_ABORTED
    # Common provider/transport error families by class-name family only.
    if any(token in name for token in ("connection", "apiconnection", "http", "ratelimit", "status")):
        return ERROR_CLASS_PROVIDER
    return ERROR_CLASS_UNKNOWN


def sanitize_error_class(error_class: Any) -> str:
    """Coerce a supplied class to the allow-list (never trust arbitrary text)."""
    value = str(error_class or "")
    return value if value in _ALLOWED_ERROR_CLASSES else ERROR_CLASS_UNKNOWN


# Allow-listed constant reason labels. Anything else maps to ``unknown_reason``
# so an arbitrary/free-text (possibly secret-bearing) string is never recorded.
_ALLOWED_REASONS = frozenset(
    {
        "clock_invalid",
        "clock_unavailable",
        "provider_usage_missing",
        "provider_usage_malformed",
        "provider_usage_conflict",
        "invocation_aborted",
        "invocation_timeout",
        "data_quality_blocked",
    }
)
REASON_UNKNOWN = "unknown_reason"


def sanitize_reason(reason: Any) -> str:
    """Coerce a supplied reason to the allow-list (no arbitrary text stored)."""
    value = str(reason or "")
    return value if value in _ALLOWED_REASONS else REASON_UNKNOWN


def resolve_audit_paths(state: Any) -> tuple[str | None, str | None]:
    """Resolve the durable failure-ledger and quarantine paths for a run.

    Prefers an explicit ``debate_failure_log_path`` / ``debate_partial_audit_path``
    on the state. When absent, derives safe defaults under the run's
    ``results_dir`` from its identity (ticker + trade_date) so a real run writes
    to a durable location. Returns ``(None, None)`` when no base directory is
    available (e.g. an offline unit test with no results_dir) — never inventing a
    path outside the configured results directory.
    """
    if not isinstance(state, dict):
        return None, None
    failure = state.get("debate_failure_log_path")
    quarantine = state.get("debate_partial_audit_path")
    base = state.get("results_dir")
    if (failure and quarantine) or not base:
        return (str(failure) if failure else None, str(quarantine) if quarantine else None)
    try:
        ticker = _safe_component(state.get("company_of_interest") or state.get("ticker") or "unknown")
        trade_date = _safe_component(state.get("trade_date") or "unknown")
        root = Path(str(base)).expanduser() / ticker / trade_date / "audit"
        if not failure:
            failure = str(root / "debate_failure_ledger.jsonl")
        if not quarantine:
            quarantine = str(root / "partial_debate_audit.jsonl")
    except (OSError, ValueError):
        return (str(failure) if failure else None, str(quarantine) if quarantine else None)
    return (str(failure) if failure else None, str(quarantine) if quarantine else None)


def _safe_component(value: Any) -> str:
    """Reduce an identity component to a safe filesystem token (no traversal)."""
    text = str(value or "").strip().lower()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    token = "".join(ch for ch in text if ch in allowed).strip(".")
    return token or "unknown"


def build_failure_record(
    *,
    run_id: str | None,
    turn: str | None,
    speaker: str | None,
    phase: str | None,
    error: BaseException | None = None,
    error_class: str | None = None,
    reason: str | None = None,
    status: str | None = None,
    usage_snapshot: Any = None,
) -> dict[str, Any]:
    """Build a JSON-safe, allow-listed failure record (no raw content)."""
    safe_usage: dict[str, Any] = {}
    if isinstance(usage_snapshot, dict):
        for key in _SAFE_USAGE_KEYS:
            if key in usage_snapshot:
                value = usage_snapshot[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                number = float(value)
                if math.isfinite(number) and number >= 0:
                    safe_usage[key] = int(number) if number == int(number) else number
        # Explicit unavailable token/time telemetry with allow-listed provenance.
        for key in ("tokens_available", "seconds_available"):
            if key in usage_snapshot:
                safe_usage[key] = bool(usage_snapshot[key])
        for key in ("tokens_source", "seconds_source"):
            value = usage_snapshot.get(key)
            if value in (SOURCE_UNAVAILABLE, "estimated"):
                safe_usage[key] = value
    record: dict[str, Any] = {
        "run_id": str(run_id) if run_id is not None else None,
        "turn": str(turn) if turn is not None else None,
        "speaker": str(speaker) if speaker is not None else None,
        "phase": str(phase) if phase is not None else None,
        "error_class": sanitize_error_class(
            error_class if error_class is not None else classify_error(error)
        ),
        "safe_usage": safe_usage,
    }
    if status is not None:
        record["status"] = _sanitize_status(status)
    if reason is not None:
        # ``reason`` must be an allow-listed constant; arbitrary/free text (which
        # could carry secret characters) is never stored.
        record["reason"] = sanitize_reason(reason)
    return record


_ALLOWED_STATUSES = frozenset(
    {
        STATUS_CLOCK_ABORT,
        STATUS_INVOKE_FAILED,
        STATUS_CLOCK_END_INVALID,
        STATUS_COMPLETED,
    }
)


def _sanitize_status(status: Any) -> str:
    value = str(status or "")
    return value if value in _ALLOWED_STATUSES else STATUS_INVOKE_FAILED


def append_failure_record(path: str | Path | None, record: dict[str, Any]) -> bool:
    """Append one sanitized record as a JSONL line. Returns ``True`` if written.

    A ``None``/empty path is a no-op (``False``) so default runs never write.
    The directory is created when needed. Only the allow-listed record produced
    by :func:`build_failure_record` is serialized.
    """
    if not path:
        return False
    target = Path(path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return True
    except OSError:
        # A ledger write failure must never convert an abort into a different
        # failure mode; the caller already re-raises the original exception.
        return False


def record_failure(
    path: str | Path | None,
    *,
    run_id: str | None,
    turn: str | None,
    speaker: str | None,
    phase: str | None,
    error: BaseException | None = None,
    error_class: str | None = None,
    reason: str | None = None,
    status: str | None = None,
    usage_snapshot: Any = None,
) -> dict[str, Any]:
    """Build and (when a path is given) append a sanitized failure record."""
    record = build_failure_record(
        run_id=run_id,
        turn=turn,
        speaker=speaker,
        phase=phase,
        error=error,
        error_class=error_class,
        reason=reason,
        status=status,
        usage_snapshot=usage_snapshot,
    )
    append_failure_record(path, record)
    return record


def build_attempted_usage(
    current_usage: Any,
    *,
    attempted: bool,
    turn_index: int | None,
) -> dict[str, Any]:
    """The safe usage snapshot the failure ledger records for an attempt.

    ``attempted`` distinguishes:

    - ``False`` — a before-invoke clock abort: **zero** actual calls were made,
      so ``calls``/``failed_calls`` are NOT incremented.
    - ``True`` — the model invocation was actually attempted and failed (or the
      end clock was invalid after an attempted call): one logical attempted call
      is counted and ``failed_calls`` becomes 1. NO tokens/time are fabricated
      (token/time availability is recorded as unavailable via provenance).

    ``turn_index`` is carried for correlation. The returned dict is JSON-safe and
    contains only allow-listed numeric scalars.
    """
    usage = dict(current_usage) if isinstance(current_usage, dict) else {}
    calls = int(usage.get("calls", 0) or 0)
    failed = int(usage.get("failed_calls", 0) or 0)
    if attempted:
        calls += 1
        failed += 1
    snapshot = {
        "calls": calls,
        "failed_calls": failed,
        "transport_attempts": usage.get("transport_attempts"),
        "tokens_available": False,
        "seconds_available": False,
        "tokens_source": "unavailable",
        "seconds_source": "unavailable",
    }
    if turn_index is not None:
        snapshot["turn_index"] = int(turn_index)
    return snapshot


def iter_failure_records(path: str | Path) -> Iterable[dict[str, Any]]:
    """Yield parsed failure records from a ledger (for tests/audits)."""
    target = Path(path).expanduser()
    if not target.exists():
        return
    with open(target, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                yield parsed
