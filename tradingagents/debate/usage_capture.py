"""Run-scoped model-invocation capture binding for whole-run usage (ADR-009).

This is the *unified* accounting binding used by every model-calling node. It is
bound for exactly one run with :func:`use_usage_capture` (a ``ContextVar``, so two
concurrent runs in one process never share state — the same pattern as the ADR-008
evidence collector). When bound, :func:`instrumented_model_call` reserves durable
spend before the outbound call and settles it after, recording the outcome in the
:class:`~tradingagents.debate.usage_ledger.UsageLedger` and in the run's
in-memory aggregate. When **not** bound (e.g. a bare node unit test) it is a
transparent no-op that returns the model response unchanged, so legacy behavior is
preserved.

Design rules (see ``docs/architecture/adr/009-durable-run-usage-ledger.md``):

- **Debate invocation is counted ONCE.** The researchers go through this same
  wrapper; the run aggregate and the durable ledger are the single source of the
  debate call too — never both a node tracker and a second aggregate.
- **Reservation before, settlement after.** A reservation is written before the
  provider call; a settlement after the outcome is known. A crash between them
  leaves an ``in_flight`` reservation (unresolved possible spend) that is not
  treated as free.
- **Honest provenance.** Provider usage is parsed with the existing
  :func:`tradingagents.debate.budget.extract_provider_usage`; a missing/failed
  token cost stays ``unavailable`` (never ``0``); measured time is used only when
  a clock is supplied.
- **No content leakage.** Only allow-listed scalars reach the ledger.
"""

from __future__ import annotations

import contextlib
import itertools
import threading
import time
import uuid
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from tradingagents.debate import usage_ledger as ledger_mod
from tradingagents.debate.budget import (
    SOURCE_ESTIMATED,
    SOURCE_MEASURED,
    SOURCE_PROVIDER,
    SOURCE_UNAVAILABLE,
    estimate_tokens_from_chars,
    extract_provider_usage,
)
from tradingagents.debate.usage_ledger import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_SUCCESS,
    UsageEvent,
    UsageLedger,
)

# A stable phase label for a structured-output attempt that fell back to plain
# free text; the caller passes the phase, the fallback attempt is tagged so the
# audit can tell a fallback from a clean structured call.
FALLBACK_ATTEMPT = "fallback"


class UsageCapture:
    """Per-run accounting binding that fronts a durable :class:`UsageLedger`.

    Holds the run identity, the ledger, and an injectable monotonic clock. Each
    model invocation gets a **globally unique** ``invocation_id`` (a per-capture
    UUID prefix + monotonic counter), so a **resume that makes a genuinely new
    provider call** can never collide with an already-settled invocation from a
    prior process. Re-reading/settling the *same* invocation remains idempotent
    (the ledger keys on the identity), but a replay that actually calls the
    provider again is a NEW counted attempt, not a silently-ignored duplicate.

    The counter is per-capture, but it is combined with a fresh per-capture token
    so a restarted capture (resume) never reuses an index another capture used.
    """

    def __init__(
        self,
        *,
        run_id: str,
        ledger: UsageLedger | None,
        clock=time.monotonic,
        conversation_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.ledger = ledger
        self.clock = clock
        self.conversation_id = conversation_id or run_id
        # A fresh per-capture token so a resumed capture never reuses an
        # invocation index minted by a prior physical process. Injectable for
        # deterministic tests (via ``capture_token`` on the constructor path).
        self._capture_token = uuid.uuid4().hex
        self._counter = itertools.count()
        self._lock = threading.RLock()
        # Set true when a RESUME expected a durable ledger but it was missing /
        # unreadable. Admissions then fail closed (accounting is unknown, never
        # assumed zero).
        self.accounting_unreadable = False
        # Settled events accrued in this process; the durable ledger is the
        # source of truth and is re-read for reconciliation, so this list is a
        # convenience for callers that cannot read the ledger (e.g. a memory-only
        # capture with no ledger file).
        self._events: list[UsageEvent] = []

    # -- identity -------------------------------------------------------

    def next_invocation_id(self, phase: str) -> str:
        """Mint a globally-unique per-invocation identity (thread safe).

        Unique across **resume/restart** because it folds in a per-capture UUID
        token (not just an index that restarts at 0), so a resumed capture that
        makes a new provider call cannot reuse an already-settled invocation id.
        """
        with self._lock:
            index = next(self._counter)
        return f"{self.conversation_id}:{phase}:{self._capture_token}:{index}"

    def admission_lock(self):
        """A re-entrant lock serializing reconcile→admit→reserve.

        Used by the researchers so two concurrent invocations in the same run
        cannot both pass a stale admission check and then over-reserve. The
        lock is per-capture (per-run), matching the run-scoped budget, and is an
        ``RLock`` so the reserve step (which also takes it to mint an id) nests.
        """
        return self._lock

    # -- capture --------------------------------------------------------

    def record_success(
        self,
        *,
        invocation_id: str,
        phase: str,
        speaker: str,
        prompt_chars: int,
        response_chars: int,
        response: Any,
        measured_seconds: float | None,
        clock_reason: str | None,
        usage_response: Any = None,
    ) -> UsageEvent:
        """Settle a successful invocation with honest provider/estimate provenance.

        Provider usage is read from ``usage_response`` when supplied (the RAW
        transport AIMessage that carries ``usage_metadata``), else from ``response``.
        This is what lets a structured (Pydantic) result — which has no
        ``.content``/``usage_metadata`` — still settle with the provider's real
        token usage instead of a fabricated estimate, WITHOUT a second model call.
        """
        provider_source = usage_response if usage_response is not None else response
        provider_usage = extract_provider_usage(provider_source)
        breakdown = _token_breakdown(provider_usage, prompt_chars, response_chars)
        seconds, seconds_source = _seconds_breakdown(measured_seconds, clock_reason)
        return self._settle(
            invocation_id=invocation_id,
            phase=phase,
            speaker=speaker,
            status=STATUS_SUCCESS,
            input_tokens=breakdown["input_tokens"],
            output_tokens=breakdown["output_tokens"],
            total_tokens=breakdown["total_tokens"],
            tokens_source=breakdown["tokens_source"],
            seconds=seconds,
            seconds_source=seconds_source,
            token_source_partial=breakdown["partial"],
            provider_conflict=breakdown["conflict"],
            unresolved=False,
            input_tokens_source=breakdown["input_tokens_source"],
            output_tokens_source=breakdown["output_tokens_source"],
            conflict_originals=breakdown["conflict_originals"],
        )

    def record_failure(
        self,
        *,
        invocation_id: str,
        phase: str,
        speaker: str,
        status: str = STATUS_FAILED,
        measured_seconds: float | None = None,
        unresolved: bool = True,
    ) -> UsageEvent:
        """Settle a failed/invalid invocation as UNKNOWN cost (never zero-known).

        A failed or invalid-clock invocation has no trustworthy token cost, so its
        tokens are ``unavailable`` (``None``) and it is marked ``unresolved`` when
        the caller cannot rule out billable spend. This is exactly why the
        pre-call guard treats unresolved spend as fail-closed.
        """
        seconds, seconds_source = _seconds_breakdown(measured_seconds, None)
        return self._settle(
            invocation_id=invocation_id,
            phase=phase,
            speaker=speaker,
            status=status,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            tokens_source=SOURCE_UNAVAILABLE,
            seconds=seconds,
            seconds_source=seconds_source,
            token_source_partial=False,
            provider_conflict=False,
            unresolved=unresolved,
        )

    def _settle(self, *, unresolved: bool, provider_conflict: bool, **kwargs: Any) -> UsageEvent:
        if self.ledger is not None:
            event = self.ledger.settle(
                run_id=self.run_id,
                provider_conflict=provider_conflict,
                unresolved=unresolved,
                **kwargs,
            )
        else:
            event = UsageEvent(
                run_id=self.run_id,
                invocation_id=str(kwargs.get("invocation_id", "")),
                phase=str(kwargs.get("phase", "")),
                speaker=str(kwargs.get("speaker", "")),
                status=str(kwargs.get("status", STATUS_FAILED)),
                input_tokens=kwargs.get("input_tokens"),
                output_tokens=kwargs.get("output_tokens"),
                total_tokens=kwargs.get("total_tokens"),
                tokens_source=str(kwargs.get("tokens_source", SOURCE_UNAVAILABLE)),
                seconds=kwargs.get("seconds"),
                seconds_source=str(kwargs.get("seconds_source", SOURCE_UNAVAILABLE)),
                token_source_partial=bool(kwargs.get("token_source_partial")),
                provider_conflict=bool(provider_conflict),
                transport_attempts=None,
                unresolved=bool(unresolved),
                created_at=str(kwargs.get("created_at", "")),
                input_tokens_source=kwargs.get("input_tokens_source"),
                output_tokens_source=kwargs.get("output_tokens_source"),
                conflict_originals=list(kwargs.get("conflict_originals") or []),
            )
        self._events.append(event)
        return event

    # -- read -----------------------------------------------------------

    def settled_events(self) -> list[UsageEvent]:
        """Settled events accrued in this process (ledger is the durable source)."""
        return list(self._events)

    def reconcile(self) -> ledger_mod.RunSpend:
        """Reconcile this run's spend from the durable ledger (idempotent)."""
        if self.accounting_unreadable:
            raise ledger_mod.LedgerError("usage accounting unreadable for this run")
        if self.ledger is None:
            return ledger_mod.RunSpend(run_id=self.run_id, events=list(self._events))
        return self.ledger.read_run_spend(self.run_id)


def _token_breakdown(
    provider_usage: Any,
    prompt_chars: int,
    response_chars: int,
) -> dict[str, Any]:
    """Resolve token counts, provenance, per-side sources and conflict originals.

    Provider data wins when valid; a provider total is used directly; a partial
    provider split fills its missing side with a *labelled estimate* so the call
    is never presented as a complete provider total; nothing usable falls back to
    a labelled character estimate. A conflict uses a conservative derived total
    and raises the conflict flag; it is never labelled provider-exact.

    The returned dict carries per-side provenance so a filled estimate is NEVER
    relabelled provider, and every conflict source block (both provider blocks +
    per-call index) is preserved in ``conflict_originals`` (allow-listed scalars
    only — no content).
    """
    result: dict[str, Any] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "tokens_source": SOURCE_ESTIMATED,
        "partial": False,
        "conflict": False,
        "input_tokens_source": None,
        "output_tokens_source": None,
        "conflict_originals": [],
    }
    if isinstance(provider_usage, dict) and provider_usage.get("available"):
        in_tok = provider_usage.get("input_tokens")
        out_tok = provider_usage.get("output_tokens")
        total_tok = provider_usage.get("total_tokens")
        if provider_usage.get("conflict"):
            from tradingagents.debate.budget import derived_conflicted_total

            derived = derived_conflicted_total(provider_usage)
            result.update(
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=derived,
                tokens_source=SOURCE_ESTIMATED,
                partial=True,
                conflict=True,
                input_tokens_source=SOURCE_PROVIDER if in_tok is not None else None,
                output_tokens_source=SOURCE_PROVIDER if out_tok is not None else None,
                conflict_originals=list(provider_usage.get("originals") or []),
            )
            return result
        if total_tok is not None:
            result.update(
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=int(total_tok),
                tokens_source=SOURCE_PROVIDER,
                partial=bool(provider_usage.get("partial")),
                input_tokens_source=SOURCE_PROVIDER if in_tok is not None else None,
                output_tokens_source=SOURCE_PROVIDER if out_tok is not None else None,
            )
            return result
        if in_tok is not None and out_tok is not None:
            result.update(
                input_tokens=int(in_tok),
                output_tokens=int(out_tok),
                total_tokens=int(in_tok) + int(out_tok),
                tokens_source=SOURCE_PROVIDER,
                input_tokens_source=SOURCE_PROVIDER,
                output_tokens_source=SOURCE_PROVIDER,
            )
            return result
        # Partial: exactly one side present, no provider total. Keep the KNOWN side
        # labelled provider and fill the MISSING side from the estimate, labelling
        # ONLY that side estimated.
        if in_tok is not None:
            missing = estimate_tokens_from_chars(max(0, int(response_chars)))
            result.update(
                input_tokens=int(in_tok),
                output_tokens=None,
                total_tokens=int(in_tok) + missing,
                tokens_source=SOURCE_ESTIMATED,
                partial=True,
                input_tokens_source=SOURCE_PROVIDER,
                output_tokens_source=SOURCE_ESTIMATED,
            )
            return result
        if out_tok is not None:
            missing = estimate_tokens_from_chars(max(0, int(prompt_chars)))
            result.update(
                input_tokens=None,
                output_tokens=int(out_tok),
                total_tokens=int(out_tok) + missing,
                tokens_source=SOURCE_ESTIMATED,
                partial=True,
                input_tokens_source=SOURCE_ESTIMATED,
                output_tokens_source=SOURCE_PROVIDER,
            )
            return result
    # No usable provider data: labelled character estimate.
    estimate = estimate_tokens_from_chars(max(0, int(prompt_chars)) + max(0, int(response_chars)))
    result.update(total_tokens=estimate, tokens_source=SOURCE_ESTIMATED)
    return result


def _seconds_breakdown(measured_seconds: Any, clock_reason: Any) -> tuple[float | None, str]:
    if measured_seconds is None:
        return None, SOURCE_UNAVAILABLE
    try:
        value = float(measured_seconds)
    except (TypeError, ValueError):
        return None, SOURCE_UNAVAILABLE
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        return None, SOURCE_UNAVAILABLE
    return value, SOURCE_MEASURED


# -- ContextVar binding --------------------------------------------------

_ACTIVE: ContextVar[UsageCapture | None] = ContextVar(
    "tradingagents_active_usage_capture", default=None
)


def get_active_capture() -> UsageCapture | None:
    """The usage-capture binding for the current run, or ``None``."""
    return _ACTIVE.get()


@contextlib.contextmanager
def use_usage_capture(capture: UsageCapture) -> Iterator[UsageCapture]:
    """Bind ``capture`` for the duration of one run (restores on exit)."""
    token = _ACTIVE.set(capture)
    try:
        yield capture
    finally:
        _ACTIVE.reset(token)


# -- instrumented invocation --------------------------------------------


def instrumented_model_call(
    call: Any,
    *,
    phase: str,
    speaker: str,
    prompt_chars: int = 0,
    response_chars_hint: Any = None,
    usage_response: Any = None,
    clock: Any = time.monotonic,
    preallocated_id: str | None = None,
) -> Any:
    """Run ``call()`` with reservation-before / settlement-after accounting.

    ``call`` is a zero-argument callable that performs the outbound model call and
    returns the response (or raises). Returns exactly what ``call`` returns, so an
    instrumented node behaves identically to an uninstrumented one.

    ``usage_response`` is an optional zero-argument callable (or value) returning
    the RAW transport response that carries provider ``usage_metadata`` — used ONLY
    for token-usage settlement when ``call`` returns a parsed/typed object that
    lacks it (e.g. a Pydantic structured result). It is a hint to the SAME single
    call, never a second model invocation.

    When no capture is bound this is a transparent passthrough. When bound, a
    durable reservation is written **before** ``call`` and a settlement **after**:

    - success -> provider/estimated tokens + measured seconds where available;
    - a raised exception -> a ``failed``/unresolved settlement (unknown cost), then
      the exception is re-raised unchanged (the existing abort behavior survives);
    - an invalid end clock -> an ``invalid_clock``/unresolved settlement, then a
      :class:`CaptureClockError` is raised (fail closed, no fabricated seconds).
    """
    capture = _ACTIVE.get()
    if capture is None:
        return call()

    if preallocated_id is not None:
        # The attempt's durable reservation was already made atomically (e.g. the
        # Research Manager summary admission). Do NOT reserve a second slot; settle
        # this same invocation id.
        invocation_id = preallocated_id
    else:
        invocation_id = capture.next_invocation_id(phase)
        reserved_tokens, reserved_seconds = _reservation_estimate(capture)
        if capture.ledger is not None:
            capture.ledger.reserve(
                run_id=capture.run_id,
                invocation_id=invocation_id,
                phase=phase,
                speaker=speaker,
                reserved_tokens=reserved_tokens,
                reserved_seconds=reserved_seconds,
            )

    start = _safe_clock(clock)
    try:
        response = call()
    except BaseException:
        # Everything except a clean success is an unknown-cost failure. Keyboard
        # interrupt / cancellation maps to ``cancelled``; any other exception to
        # ``failed``. The exception is re-raised unchanged.
        status = _failure_status()
        capture.record_failure(
            invocation_id=invocation_id, phase=phase, speaker=speaker, status=status
        )
        raise
    end = _safe_clock(clock)

    measured_seconds: float | None = None
    clock_reason: str | None = None
    if start is not None and end is not None and end >= start:
        measured_seconds = end - start
    else:
        clock_reason = "clock_invalid"

    content = getattr(response, "content", "") or ""
    response_chars = len(content) if isinstance(content, str) else 0
    if response_chars == 0:
        hint = response_chars_hint() if callable(response_chars_hint) else response_chars_hint
        if hint:
            # A structured (Pydantic) result has no ``.content``; use the rendered
            # output length so the estimate is not fabricated as 0.
            response_chars = max(0, int(hint))
    capture.record_success(
        invocation_id=invocation_id,
        phase=phase,
        speaker=speaker,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        response=response,
        measured_seconds=measured_seconds,
        clock_reason=clock_reason,
        usage_response=(usage_response() if callable(usage_response) else usage_response),
    )
    if clock_reason == "clock_invalid":
        # Binding contract: the call happened but its time is unusable. The
        # success settlement recorded an honest unknown time; now fail closed on
        # the timing so no fabricated seconds propagate.
        raise CaptureClockError(
            f"{speaker} invocation timing unavailable ({clock_reason})"
        )
    return response


def _reservation_estimate(capture: UsageCapture) -> tuple[int, float]:
    """The conservative estimate reserved for one optional call (config units)."""
    config = getattr(capture, "debate_config", None)
    if config is None:
        return 0, 0.0
    from tradingagents.debate.budget import next_call_estimate

    try:
        tokens, seconds = next_call_estimate(config)
        return int(tokens), float(seconds)
    except Exception:  # noqa: BLE001 — a bad estimate never blocks accounting
        return 0, 0.0


def instrument_analyst_invoke(chain: Any, messages: Any, *, speaker: str) -> Any:
    """Instrument an analyst ``chain.invoke(messages)`` (phase ``analyst``).

    The analyst reports are produced by a bound model chain; wrapping the call
    here makes the whole-run total cover them. Prompt characters are estimated
    from the message content (best effort). A transparent passthrough when no
    capture is bound.
    """
    return instrumented_model_call(
        lambda: chain.invoke(messages),
        phase="analyst",
        speaker=speaker,
        prompt_chars=_messages_chars(messages),
    )


def _messages_chars(messages: Any) -> int:
    try:
        if isinstance(messages, (list, tuple)):
            total = 0
            for msg in messages:
                content = getattr(msg, "content", msg)
                total += len(content) if isinstance(content, str) else 0
            return total
        return len(str(messages))
    except Exception:  # noqa: BLE001 — never let accounting break a call
        return 0


def _safe_clock(clock: Any) -> float | None:
    try:
        value = clock()
    except Exception:  # noqa: BLE001 — a broken clock taints the reading
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        return None
    return number


def _failure_status() -> str:
    import sys

    exc = sys.exc_info()[1]
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return STATUS_CANCELLED
    name = type(exc).__name__.lower() if exc is not None else ""
    if "cancel" in name or "abort" in name:
        return STATUS_CANCELLED
    return STATUS_FAILED


class CaptureClockError(RuntimeError):
    """Raised when an instrumented call's end clock is unusable (fail closed)."""


class BudgetDeniedError(RuntimeError):
    """Raised when a modelled summary cannot be safely afforded (ADR-009).

    A structured-output caller that hits a budget denial must NOT swallow it into
    a free-text retry (which would spend again); the caller uses its deterministic
    fallback instead.
    """
