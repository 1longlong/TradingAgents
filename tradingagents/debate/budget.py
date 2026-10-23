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


DEBATE_USAGE_KEY = "debate_usage"


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
