"""Budget accounting and deterministic usage estimation for Phase 3B.

The Debate Evaluator must reserve Research Manager summary capacity and stop
optional debate when remaining capacity is less than the conservative
next-round estimate plus the summary reserve. When a provider does not report
token usage, a deterministic character-based estimate is used and the
``estimated`` flag is set; call count and elapsed time remain reliable
fallbacks.

Tests inject the clock/usage via :class:`UsageTracker` so accounting is fully
deterministic offline.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

# A conservative characters-per-token heuristic for char-based estimation.
_CHARS_PER_TOKEN = 4.0


def estimate_tokens_from_chars(char_count: int) -> int:
    """Deterministic character-based token estimate: ``ceil(chars / 4)``."""
    if char_count <= 0:
        return 0
    return int(-(-char_count // int(_CHARS_PER_TOKEN)))


def estimate_seconds_from_chars(char_count: int, chars_per_second: float = 30.0) -> float:
    """Deterministic estimate of generation time based on output length."""
    if char_count <= 0:
        return 0.0
    return char_count / max(1.0, chars_per_second)


# The stop reason a pre-call budget guard records when an optional debate call
# cannot be afforded without breaching a hard limit or the summary reserve.
STOP_REASON_BUDGET_EXHAUSTED = "budget_exhausted"

DEBATE_USAGE_KEY = "debate_usage"


def remaining_calls(usage: Mapping[str, Any] | None, max_calls: int) -> int:
    """Calls still available under the hard call limit (never negative)."""
    used = int((usage or {}).get("calls", 0))
    return max(0, int(max_calls) - used)


def next_call_estimate(config: Any) -> tuple[int, float]:
    """Conservative one-optional-call token/time estimate derived from config.

    The configured ``next_round_estimate_*`` describes one full Bull+Bear round
    (two calls). A single optional call is estimated as half of it, rounded
    *up* for tokens so the estimate is never optimistic. These are the same
    deterministic estimate units the evaluator uses; they are an estimate, not a
    physical provider guarantee (recorded as such in the trace).
    """
    round_tokens = int(getattr(config, "next_round_estimate_tokens", 0))
    round_seconds = float(getattr(config, "next_round_estimate_seconds", 0.0))
    per_call_tokens = (round_tokens + 1) // 2 if round_tokens else 0
    per_call_seconds = round_seconds / 2 if round_seconds else 0.0
    return per_call_tokens, per_call_seconds


def can_afford_optional_call(
    usage: Mapping[str, Any] | None,
    config: Any,
) -> bool:
    """Conservative *pre-call* admission check for one optional debate call.

    Called before every Bull/Bear invocation so an optional call that would
    breach the call hard limit, consume the reserved summary capacity, or — in
    estimated units — leave too little room after paying for the estimated
    next-call cost is never made at all (design sections 1.2/4.6/4.9/7.2).

    Three independent checks must pass:

    1. **Call hard limit** — one call must remain (debate calls only; this is
       *not* a total-run budget, and a total-run call count is not tracked
       here).
    2. **Summary reserve** — the remaining capacity must still cover the reserve
       after the estimated cost of this optional call, i.e. remaining >=
       ``reserved_summary_* + next_call_estimate_*``. Comparing remaining only
       to the reserve is wrong: if every remaining token is the reserve, an
       optional call would eat it.
    3. The token/time figures are deterministic **estimates**, not physical
       provider guarantees; the reserve comparison is expressed in the same
       estimate units and is therefore the honest configured check.

    A disabled config (``enabled=False``) reproduces legacy behavior and always
    permits the call so the fixed-round baseline is unchanged.
    """
    if not getattr(config, "enabled", True):
        return True
    max_calls = int(getattr(config, "max_calls", 0))
    if remaining_calls(usage, max_calls) < 1:
        return False
    used = usage or {}
    used_tokens = int(used.get("tokens", 0))
    used_seconds = float(used.get("seconds", 0.0))
    reserve_tokens = int(getattr(config, "reserved_summary_tokens", 0))
    reserve_seconds = float(getattr(config, "reserved_summary_seconds", 0.0))
    max_tokens = int(getattr(config, "max_tokens", 0))
    max_time = float(getattr(config, "max_time", 0.0))
    call_tokens, call_seconds = next_call_estimate(config)
    # The reserve plus this optional call's estimated cost must still fit.
    if max_tokens - used_tokens < reserve_tokens + call_tokens:
        return False
    return max_time - used_seconds >= reserve_seconds + call_seconds


def budget_admission_decision(
    *,
    next_speaker: str,
    calls_used: int,
    max_calls: int,
    config: Any = None,
    usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-safe decision the graph records when a pre-call guard refuses a call.

    Routes to the Research Manager with ``budget_exhausted`` so the run safely
    skips to the manager summary instead of executing an over-budget optional
    call. The trace records the observed call count against the hard limit and,
    when config/usage are supplied, the reserve + estimated next-call comparison
    that justified the refusal. Token/time figures are explicitly labelled
    ``estimate_basis: "estimated"`` — they are the configured estimate check, not
    a physical provider guarantee, and call limits concern debate calls only
    (not total-run budget).
    """
    thresholds: dict[str, Any] = {"max_calls": int(max_calls)}
    actual: dict[str, Any] = {
        "calls_used": int(calls_used),
        "refused_speaker": next_speaker,
    }
    if config is not None:
        call_tokens, call_seconds = next_call_estimate(config)
        used = usage or {}
        thresholds.update(
            {
                "reserved_summary_tokens": int(getattr(config, "reserved_summary_tokens", 0)),
                "reserved_summary_seconds": float(getattr(config, "reserved_summary_seconds", 0.0)),
                "next_call_estimate_tokens": call_tokens,
                "next_call_estimate_seconds": call_seconds,
                "max_tokens": int(getattr(config, "max_tokens", 0)),
                "max_time": float(getattr(config, "max_time", 0.0)),
            }
        )
        actual.update(
            {
                "used_tokens": int(used.get("tokens", 0) or 0),
                "used_seconds": float(used.get("seconds", 0.0) or 0.0),
                "estimate_basis": "estimated",
                "scope": "debate_calls_only",
            }
        )
    return {
        "route": "summarize",
        "stop_reason": STOP_REASON_BUDGET_EXHAUSTED,
        "next_speaker": "",
        "trace": [
            {
                "rule": "budget_precall",
                "activated": True,
                "thresholds": thresholds,
                "actual": actual,
            }
        ],
    }


def empty_usage() -> dict[str, Any]:
    """The deterministic run-level usage dict a fresh run starts with."""
    return {"calls": 0, "tokens": 0, "seconds": 0.0, "estimated": False}


def record_call_usage(
    current_usage: Mapping[str, Any] | None,
    *,
    prompt_chars: int,
    response_chars: int,
    exact_tokens: int | None = None,
    exact_seconds: float | None = None,
    char_estimator: Callable[[int], int] = estimate_tokens_from_chars,
    time_estimator: Callable[[int], float] = estimate_seconds_from_chars,
) -> dict[str, Any]:
    """Accrue one LLM call onto a run-level usage dict (JSON-safe, additive).

    This is the single place a Bull/Bear researcher records its call so the
    Debate Evaluator reads real consumption — not zeros. Call count always
    increments by one. Tokens/seconds come from ``exact_*`` when the provider
    reports them, otherwise a documented character-based estimate is used and
    ``estimated`` is set to ``True``. ``seconds`` is an estimate derived from
    output length (no wall-clock coupling), so the trace is reproducible.
    """
    usage = dict(current_usage) if current_usage else empty_usage()
    usage["calls"] = int(usage.get("calls", 0)) + 1
    total_chars = max(0, int(prompt_chars)) + max(0, int(response_chars))
    token_estimate = char_estimator(total_chars)
    seconds_estimate = time_estimator(total_chars)
    if exact_tokens is not None:
        usage["tokens"] = int(usage.get("tokens", 0)) + int(exact_tokens)
    else:
        usage["tokens"] = int(usage.get("tokens", 0)) + token_estimate
    if exact_seconds is not None:
        usage["seconds"] = float(usage.get("seconds", 0.0)) + float(exact_seconds)
    else:
        usage["seconds"] = float(usage.get("seconds", 0.0)) + seconds_estimate
    if exact_tokens is None or exact_seconds is None:
        usage["estimated"] = True
    return usage


def resolve_budget_config_from_state(
    state: Mapping[str, Any],
    injected_config: Any = None,
) -> Any:
    """Resolve the effective ``debate_termination`` config for a pre-call guard.

    Prefers the injected config (the graph passes the validated group), then a
    resolved group carried on the state (``debate_termination_config`` dict), then
    the defaults. This keeps the pre-call guard consistent with the evaluator
    without re-reading the root config in every researcher call.
    """
    if injected_config is not None:
        return injected_config
    from tradingagents.debate.config import resolve_debate_termination_config

    root = {
        "debate_termination": state.get("debate_termination_config"),
        "max_debate_rounds": state.get("max_debate_rounds"),
    }
    return resolve_debate_termination_config(root)


class UsageTracker:
    """Injectable accounting for calls, tokens, and elapsed time.

    ``char_estimator`` / ``time_estimator`` are injected so tests use
    deterministic estimates without touching a live provider. When the provider
    reports usage, callers pass exact values to ``record`` with
    ``estimated=False``; otherwise they pass the estimated values with
    ``estimated=True``.
    """

    def __init__(
        self,
        *,
        char_estimator: Callable[[int], int] = estimate_tokens_from_chars,
        time_estimator: Callable[[int], float] = estimate_seconds_from_chars,
    ) -> None:
        self.char_estimator = char_estimator
        self.time_estimator = time_estimator
        self.calls = 0
        self.tokens = 0
        self.seconds = 0.0
        self.estimated = False

    def record_usage(
        self,
        *,
        calls: int = 1,
        prompt_chars: int = 0,
        response_chars: int = 0,
        exact_tokens: int | None = None,
        exact_seconds: float | None = None,
    ) -> None:
        """Accrue usage for one (or more) LLM calls.

        When ``exact_tokens``/``exact_seconds`` are supplied they are used
        verbatim (and ``estimated`` stays whatever it was unless this call was
        exact); otherwise the char-based estimates are used and ``estimated`` is
        set to ``True``.
        """
        self.calls += int(calls)
        token_estimate = self.char_estimator(prompt_chars + response_chars)
        seconds_estimate = self.time_estimator(prompt_chars + response_chars)
        if exact_tokens is not None:
            self.tokens += int(exact_tokens)
        else:
            self.tokens += token_estimate
        if exact_seconds is not None:
            self.seconds += float(exact_seconds)
        else:
            self.seconds += seconds_estimate
        if exact_tokens is None or exact_seconds is None:
            self.estimated = True

    def snapshot(self) -> dict[str, Any]:
        """Current usage as a JSON-safe dict."""
        return {
            "calls": self.calls,
            "tokens": self.tokens,
            "seconds": self.seconds,
            "estimated": self.estimated,
        }
