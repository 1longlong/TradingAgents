"""Shared debate-invocation accounting for the Bull/Bear researchers (ADR-009).

The researchers previously recorded usage in an in-memory ``debate_usage`` dict
that LangGraph discards when a node raises. Stage 2 makes the spend durable: when
a run-scoped usage capture is bound (the normal production graph), each debate
invocation is

1. **reserved** in the durable ledger BEFORE the outbound call, and
2. **settled** in the ledger as soon as its outcome is known — before the node
   returns its state update — so a crash after the provider succeeds but before
   the checkpoint cannot lose the spend.

``debate_usage`` is then **derived from the ledger** for the run (idempotent on
resume; never double-adds), and any still-``in_flight`` reservation is surfaced as
unresolved spend so the pre-call guard fails closed.

When no capture is bound (a bare unit test that calls the node directly) the
researcher falls back to the legacy in-memory ``record_call_usage`` path so the
existing behavior and tests are preserved.
"""

from __future__ import annotations

from typing import Any

from tradingagents.debate import usage_capture as capture_mod
from tradingagents.debate.budget import (
    SOURCE_UNAVAILABLE,
    derive_debate_usage_from_events,
    extract_provider_usage,
    record_call_usage,
    validate_clock_elapsed,
)


def _read_clock(clock) -> float | None:
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


def has_durable_capture() -> bool:
    """True when a run-scoped durable usage capture is bound."""
    return capture_mod.get_active_capture() is not None


def reserve_invocation(speaker: str) -> str | None:
    """Reserve possible spend for one debate invocation (before the call).

    Returns the ``invocation_id`` (used to settle) or ``None`` when no durable
    capture is bound. The reservation is written even if the caller then crashes,
    so the attempt is never treated as free.
    """
    capture = capture_mod.get_active_capture()
    if capture is None:
        return None
    phase = "debate"
    invocation_id = capture.next_invocation_id(phase)
    if capture.ledger is not None:
        from tradingagents.debate.budget import next_call_estimate

        config = getattr(capture, "debate_config", None)
        if config is not None:
            tokens, seconds = next_call_estimate(config)
        else:
            tokens, seconds = 0, 0.0
        capture.ledger.reserve(
            run_id=capture.run_id,
            invocation_id=invocation_id,
            phase=phase,
            speaker=speaker,
            reserved_tokens=int(tokens),
            reserved_seconds=float(seconds),
        )
    return invocation_id


def settle_success(
    invocation_id: str | None,
    speaker: str,
    response: Any,
    *,
    prompt_chars: int,
    response_chars: int,
    measured_seconds: float | None,
    clock_reason: str | None,
) -> None:
    """Settle a successful debate invocation in the durable ledger (if bound)."""
    if invocation_id is None:
        return
    capture = capture_mod.get_active_capture()
    if capture is None:
        return
    capture.record_success(
        invocation_id=invocation_id,
        phase="debate",
        speaker=speaker,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        response=response,
        measured_seconds=measured_seconds,
        clock_reason=clock_reason,
    )


def settle_failure(
    invocation_id: str | None,
    speaker: str,
    *,
    status: str,
    measured_seconds: float | None = None,
    unresolved: bool = True,
) -> None:
    """Settle a failed/invalid debate invocation as unknown cost (if bound)."""
    if invocation_id is None:
        return
    capture = capture_mod.get_active_capture()
    if capture is None:
        return
    capture.record_failure(
        invocation_id=invocation_id,
        phase="debate",
        speaker=speaker,
        status=status,
        measured_seconds=measured_seconds,
        unresolved=unresolved,
    )


def derive_debate_usage(state: dict[str, Any]) -> dict[str, Any] | None:
    """Reconcile ``debate_usage`` from the durable ledger (or ``None`` unpinned).

    Returns ``None`` when no durable capture is bound so the caller keeps the
    legacy in-memory path. When bound, the returned dict is the whole-run's
    debate-phase spend derived from the ledger — idempotent on resume — with any
    unresolved ``in_flight`` reservation folded in as fail-closed spend. An
    unreadable ledger is surfaced as ``accounting_unreadable`` (never zeroed).
    """
    capture = capture_mod.get_active_capture()
    if capture is None:
        return None
    from tradingagents.debate.usage_ledger import LedgerError

    try:
        spend = capture.reconcile()
        return derive_debate_usage_from_events(spend.events, unresolved=spend.unresolved)
    except LedgerError:
        legacy = state.get("debate_usage") if isinstance(state, dict) else None
        usage = dict(legacy) if isinstance(legacy, dict) else {}
        usage["accounting_unreadable"] = True
        usage.setdefault("provenance", {"tokens": SOURCE_UNAVAILABLE, "seconds": SOURCE_UNAVAILABLE})
        return usage


def accumulate_legacy_usage(
    state: dict[str, Any],
    *,
    prompt_chars: int,
    response_chars: int,
    response: Any,
    measured_seconds: float,
) -> dict[str, Any]:
    """The legacy in-memory path used only when no durable capture is bound."""
    provider_usage = extract_provider_usage(response)
    return record_call_usage(
        state.get("debate_usage"),
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        provider_usage=provider_usage,
        measured_seconds=measured_seconds,
    )


def clock_check(start: Any, end: Any) -> dict[str, Any]:
    return validate_clock_elapsed(start, end)


def summary_affordable(state: dict[str, Any], config: Any) -> bool:
    """True when the Research Manager summary can be afforded safely (ADR-009).

    The summary is the mandatory report step; it must run only after a proven safe
    reserve remains, accounting ALL debate + prior Research-Manager spend (so a
    failed structured summary taints a fallback admission). It uses
    :func:`can_afford_summary` — which admits when the remaining budget still
    covers the **reserved summary allowance only** (the summary consumes the
    reserve; it does not need a second optional-call estimate) and fails closed on
    unresolved possible spend. When no durable capture is bound (or the budget is
    disabled) the summary is always considered affordable so the legacy behavior is
    preserved.
    """
    capture = capture_mod.get_active_capture()
    if capture is None or not getattr(config, "enabled", True):
        return True
    from tradingagents.debate.budget import (
        can_afford_summary,
        derive_debate_usage_from_events,
    )

    try:
        spend = capture.reconcile()
        scope = derive_debate_usage_from_events(
            spend.events,
            unresolved=spend.unresolved,
            phases=("debate", "research_manager"),
        )
    except Exception:  # noqa: BLE001 — unreadable accounting fails closed
        scope = {"accounting_unreadable": True, "unresolved_invocations": 1}
    return can_afford_summary(scope, config)


def admit_summary_attempt(state: dict[str, Any], config: Any) -> str | None:
    """Atomically admit + reserve ONE summary attempt (or return ``None`` = denied).

    Re-checks affordability under the capture lock and, when a durable ledger is
    bound, reserves the summary attempt through the ledger's ``BEGIN IMMEDIATE``
    transaction (:meth:`UsageLedger.admit_summary_call`) so concurrent capture/
    ledger instances cannot both exceed the call cap. Returns the reserved
    invocation id (caller must settle it) or ``None`` when denied. When no durable
    capture is bound, returns ``None`` iff not affordable, else a sentinel
    empty-string id so the caller proceeds on the memory-only path.
    """
    capture = capture_mod.get_active_capture()
    if capture is None:
        from tradingagents.debate.budget import (
            can_afford_summary,
            derive_debate_usage_from_events,
        )

        if not getattr(config, "enabled", True):
            return ""
        usage = state.get("debate_usage") if isinstance(state, dict) else None
        return "" if can_afford_summary(usage, config) else None

    from tradingagents.debate.budget import (
        can_afford_summary,
        derive_debate_usage_from_events,
        next_call_estimate,
    )

    with capture.admission_lock():
        if not getattr(config, "enabled", True):
            return ""
        invocation_id = capture.next_invocation_id("research_manager")
        if capture.ledger is None:
            # Memory-only: still apply the fresh in-process affordability check.
            try:
                spend = capture.reconcile()
                scope = derive_debate_usage_from_events(
                    spend.events,
                    unresolved=spend.unresolved,
                    phases=("debate", "research_manager"),
                )
            except Exception:  # noqa: BLE001 — unreadable accounting fails closed
                return None
            return invocation_id if can_afford_summary(scope, config) else None
        est_tokens, est_seconds = next_call_estimate(config)
        try:
            # The FULL policy (call slot + token/time + reserve + unresolved) is
            # re-read and evaluated INSIDE the ledger's BEGIN IMMEDIATE transaction.
            admitted = capture.ledger.admit_summary_call(
                run_id=capture.run_id,
                invocation_id=invocation_id,
                max_calls=int(getattr(config, "max_calls", 0)),
                reserved_tokens=int(est_tokens),
                reserved_seconds=float(est_seconds),
                speaker="Research Manager",
                config=config,
            )
        except Exception:  # noqa: BLE001 — unreadable accounting fails closed
            return None
        return invocation_id if admitted else None


def reconcile_debate_usage(state: dict[str, Any]) -> dict[str, Any] | None:
    """The ledger-reconciled debate usage for admission, or ``None`` (legacy).

    Returns ``None`` when no durable capture is bound so the legacy in-memory
    ``state["debate_usage"]`` path is used. When bound, reconciliation happens
    BEFORE the pre-call admission check so a stale checkpoint ``debate_usage`` can
    never admit a further OPTIONAL call after an unresolved/failed spend.
    """
    return derive_debate_usage(state)


def admit_and_reserve(
    state: dict[str, Any],
    speaker: str,
    config: Any,
    *,
    can_afford: Any,
    admission_decision: Any,
) -> tuple[dict[str, Any], str | None]:
    """Atomically reconcile usage, run admission, and reserve if admitted.

    Returns ``(admission, invocation_id)``:

    - ``admission`` is ``{}`` when admitted (the caller proceeds) or a
      ``debate_termination_decision`` delta when refused;
    - ``invocation_id`` is the reserved durable invocation id when a durable
      capture is bound and the call was admitted, else ``None``.

    The whole reconcile→admit→reserve sequence runs under the capture lock, AND
    the reservation is inserted through the ledger's ``BEGIN IMMEDIATE``
    transaction (:meth:`UsageLedger.admit_debate_call`) so two independent
    capture/ledger instances opening the SAME run database (concurrent
    resumes/processes) cannot both pass the hard CALL limit and over-reserve: at
    most one wins the last slot. When no durable capture is bound this reproduces
    the legacy admission check exactly.
    """
    capture = capture_mod.get_active_capture()
    if capture is None:
        usage = state.get("debate_usage")
        if not can_afford(usage, config):
            return (
                admission_decision(
                    next_speaker=speaker,
                    calls_used=int((usage or {}).get("calls", 0)),
                    max_calls=int(config.max_calls),
                    config=config,
                    usage=usage,
                ),
                None,
            )
        return {}, None

    with capture.admission_lock():
        reconciled = derive_debate_usage(state)
        if reconciled is None:
            reconciled = state.get("debate_usage")
        invocation_id = capture.next_invocation_id("debate")
        admitted = True
        if capture.ledger is not None:
            from tradingagents.debate.budget import next_call_estimate

            debate_config = getattr(capture, "debate_config", None)
            if debate_config is not None:
                est_tokens, est_seconds = next_call_estimate(debate_config)
            else:
                est_tokens, est_seconds = 0, 0.0
            try:
                # The FULL policy (call limit + token/time capacity + reserve +
                # unresolved spend) is re-read from rows and evaluated INSIDE the
                # ledger's BEGIN IMMEDIATE transaction, so two independent
                # capture/ledger instances cannot both pass a stale preflight.
                admitted = capture.ledger.admit_debate_call(
                    run_id=capture.run_id,
                    invocation_id=invocation_id,
                    max_calls=int(getattr(config, "max_calls", 0)),
                    reserved_tokens=int(est_tokens),
                    reserved_seconds=float(est_seconds),
                    speaker=speaker,
                    config=config,
                )
            except Exception:  # noqa: BLE001 — unreadable accounting fails closed
                admitted = False
        else:
            # Memory-only: apply the fresh in-process affordability check.
            admitted = can_afford(reconciled, config)
        if not admitted:
            return (
                admission_decision(
                    next_speaker=speaker,
                    calls_used=int((reconciled or {}).get("calls", 0)),
                    max_calls=int(config.max_calls),
                    config=config,
                    usage=reconciled,
                ),
                None,
            )
    return {}, invocation_id
