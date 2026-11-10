"""Budget accounting and deterministic usage estimation for Phase 3B.

The Debate Evaluator must reserve Research Manager summary capacity and stop
optional debate when remaining capacity is less than the conservative
next-round estimate plus the summary reserve. When a provider does not report
token usage, a deterministic character-based estimate is used and the
``estimated`` flag is set.

Elapsed time is treated differently from tokens: the repair premise is that a
real Bull/Bear call is timed with a measured (injectable) monotonic clock, and
runtime elapsed time is **never** derived from prompt/output characters. When
the caller supplies a measured elapsed time it is used verbatim; when the caller
supplies none the elapsed time is recorded as *unavailable* (never invented as
zero and never character-estimated). Token counts may still fall back to a
labelled character-based estimate when the provider reports none.

Tests inject the clock/usage via :class:`UsageTracker` so accounting is fully
deterministic offline.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

# A conservative characters-per-token heuristic for char-based estimation.
_CHARS_PER_TOKEN = 4.0

# Per-field provenance sources. A value is only ever labelled ``measured`` (time
# from the injected clock) or ``provider`` (a valid provider-reported token
# count). ``estimated`` is a laballed fallback; ``missing``/``unavailable`` mean
# the field was not obtained (never fabricated as zero).
SOURCE_MEASURED = "measured"
SOURCE_PROVIDER = "provider"
SOURCE_ESTIMATED = "estimated"
SOURCE_MISSING = "missing"
SOURCE_UNAVAILABLE = "unavailable"

# Constant reasons a caller may attach to an unavailable/estimated field. These
# are allow-listed constants (never free-form exception strings).
REASON_CLOCK_INVALID = "clock_invalid"
REASON_CLOCK_UNAVAILABLE = "clock_unavailable"
REASON_USAGE_MISSING = "provider_usage_missing"
REASON_USAGE_MALFORMED = "provider_usage_malformed"
REASON_USAGE_CONFLICT = "provider_usage_conflict"

_CALL_STATUS_COMPLETED = "completed"
_CALL_STATUS_FAILED = "failed"


def estimate_tokens_from_chars(char_count: int) -> int:
    """Deterministic character-based token estimate: ``ceil(chars / 4)``."""
    if char_count <= 0:
        return 0
    return int(-(-char_count // int(_CHARS_PER_TOKEN)))


def estimate_seconds_from_chars(char_count: int, chars_per_second: float = 30.0) -> float:
    """DERIVED-ONLY (deprecated) character-based time estimate.

    Kept for callers that never had a measured clock (e.g. the comparison
    fixtures). It is **not** used for debate runtime accounting: a real
    Bull/Bear call is timed with the injectable clock, and a missing/invalid
    clock is recorded as *unavailable* rather than revived from characters.
    """
    if char_count <= 0:
        return 0.0
    return char_count / max(1.0, chars_per_second)


def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite (non-bool) float, or ``None`` if not valid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def valid_token_count(value: Any) -> int | None:
    """A valid non-negative integer token count, or ``None``.

    Rejects ``bool`` (a subclass of ``int``), floats that are not integral,
    negatives and non-finite values so a malformed provider field never becomes
    a fabricated count. A legitimate ``0`` is returned as ``0``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = _finite_number(value)
    if number is None or number < 0 or number != int(number):
        return None
    return int(number)


def _usage_mapping(candidate: Any) -> Mapping[str, Any] | None:
    if isinstance(candidate, Mapping):
        return candidate
    return None


def _read_usage_fields(mapping: Mapping[str, Any], in_key: str, out_key: str, total_key: str) -> dict[str, Any]:
    return {
        "input_tokens": valid_token_count(mapping.get(in_key)),
        "output_tokens": valid_token_count(mapping.get(out_key)),
        "total_tokens": valid_token_count(mapping.get(total_key)),
    }


def extract_provider_usage(response: Any) -> dict[str, Any]:
    """Extract provider-reported token usage from an LLM response, honestly.

    Reads LangChain ``usage_metadata`` (``input_tokens`` / ``output_tokens`` /
    ``total_tokens``) and a nested ``response_metadata["token_usage"]`` or
    ``response_metadata["usage"]`` (``prompt_tokens`` / ``completion_tokens`` /
    ``total_tokens``). When BOTH source blocks are present they are reconciled:
    identical fields agree; any disagreement retains the originals and raises
    the ``conflict`` flag (never silently dropping one side).

    Only non-negative integral finite values are trusted; ``bool``, negative,
    non-finite or non-integral values are ignored (never coerced).

    Returns a JSON-safe dict::

        {
          "input_tokens": int | None,
          "output_tokens": int | None,
          "total_tokens": int | None,   # provider-reported total only
          "total_source": "provider" | None,
          "available": bool,            # any provider field was trustworthy
          "partial": bool,              # only ONE of input/output is present
          "conflict": bool,             # sources or total vs components disagree
          "reason": str | None,         # constant reason when nothing usable
        }

    A valid provider ``total_tokens`` alone is usable even when the input/output
    components are missing (the missing components stay ``None``). An
    *input-only* or *output-only* count is NOT a complete exact total: it is
    reported as ``partial`` so a caller fills only the missing side with a
    labelled estimate (or derives a conservative total) rather than treating the
    one-sided value as the full provider total. When the provider total disagrees
    with ``input_tokens + output_tokens`` both original values are retained and
    ``conflict`` is set; no side is silently dropped.
    """
    result: dict[str, Any] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "total_source": None,
        "available": False,
        "partial": False,
        "conflict": False,
        "originals": [],
        "reason": None,
    }
    if response is None:
        result["reason"] = REASON_USAGE_MISSING
        return result

    sources: list[dict[str, Any]] = []
    usage_md = _usage_mapping(getattr(response, "usage_metadata", None))
    if usage_md is not None:
        fields = _read_usage_fields(usage_md, "input_tokens", "output_tokens", "total_tokens")
        if any(v is not None for v in fields.values()):
            sources.append({"source": "usage_metadata", **fields})

    response_md = _usage_mapping(getattr(response, "response_metadata", None))
    malformed = False
    if response_md is not None:
        token_usage = _usage_mapping(response_md.get("token_usage")) or _usage_mapping(
            response_md.get("usage")
        )
        if token_usage is not None:
            fields = _read_usage_fields(
                token_usage, "prompt_tokens", "completion_tokens", "total_tokens"
            )
            if any(v is not None for v in fields.values()):
                sources.append({"source": "response_metadata.token_usage", **fields})
        elif any(key in response_md for key in ("token_usage", "usage")):
            malformed = True

    if not sources:
        result["reason"] = REASON_USAGE_MALFORMED if malformed else REASON_USAGE_MISSING
        return result

    # Reconcile the source blocks. Identical values agree; disagreement between
    # sources is a conflict. We keep the conservative (max) per field so the
    # budget never under-counts, while retaining the source-labelled ORIGINALS so
    # no source's values are lost.
    conflict = False
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        values = {src[field] for src in sources if src[field] is not None}
        if len(values) > 1:
            conflict = True
            result[field] = max(values)
        elif len(values) == 1:
            result[field] = next(iter(values))
    # Preserve every source's original (already field-normalized) values, labelled
    # by which provider block produced them, so the persisted provenance/report
    # can carry them (not only the max) and can tell the sources apart.
    result["originals"] = [dict(src) for src in sources]

    result["available"] = True
    if result["total_tokens"] is not None:
        result["total_source"] = SOURCE_PROVIDER
    in_tok = result["input_tokens"]
    out_tok = result["output_tokens"]
    result["partial"] = (in_tok is None) != (out_tok is None)
    return _finalize_provider_usage(result, conflict=conflict)


def _finalize_provider_usage(result: dict[str, Any], *, conflict: bool = False) -> dict[str, Any]:
    """Flag a conflict when a provider total disagrees with its components."""
    in_tok = result["input_tokens"]
    out_tok = result["output_tokens"]
    total_tok = result["total_tokens"]
    if total_tok is not None and in_tok is not None and out_tok is not None and total_tok != in_tok + out_tok:
        conflict = True
    if conflict:
        result["conflict"] = True
        result["reason"] = REASON_USAGE_CONFLICT
    return result


def derived_conflicted_total(provider_usage: Mapping[str, Any]) -> int | None:
    """A conservative *derived* total for budget use when provider data conflicts.

    Only called when ``provider_usage["conflict"]`` is true. Uses ``max`` of the
    provider total and the component sum so the budget guard never under-counts.
    The caller MUST label this value ``derived``/``conflicted`` — it is never
    provider-exact.
    """
    total_tok = provider_usage.get("total_tokens")
    in_tok = provider_usage.get("input_tokens")
    out_tok = provider_usage.get("output_tokens")
    candidates = [v for v in (total_tok, (in_tok + out_tok if in_tok is not None and out_tok is not None else None)) if v is not None]
    if not candidates:
        return None
    return int(max(candidates))


def validate_clock_elapsed(start: Any, end: Any) -> dict[str, Any]:
    """Validate a measured ``end - start`` elapsed time, failing closed.

    A measured monotonic clock can still yield an unusable reading: ``start``/
    ``end`` non-numeric, non-finite, or ``end < start`` (a backwards clock). Any
    such case returns ``{"ok": False, "seconds": None, "reason": <constant>}`` —
    the caller must record elapsed time as *unavailable* and abort/refuse to
    imply a runtime; it must NOT fall back to character-based time or invent
    zero.

    Monotonic validation is strictly ``end >= start``. A *shorter* second
    invocation than a previous one is perfectly valid (calls have different
    durations) and is never treated as a backwards clock.

    On success returns ``{"ok": True, "seconds": <float>, "reason": None}``.
    """
    start_num = _finite_number(start)
    end_num = _finite_number(end)
    if start_num is None or end_num is None:
        return {"ok": False, "seconds": None, "reason": REASON_CLOCK_INVALID}
    if start_num < 0 or end_num < 0:
        return {"ok": False, "seconds": None, "reason": REASON_CLOCK_INVALID}
    elapsed = end_num - start_num
    if not math.isfinite(elapsed) or elapsed < 0:
        return {"ok": False, "seconds": None, "reason": REASON_CLOCK_INVALID}
    return {"ok": True, "seconds": elapsed, "reason": None}


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
        provenance = used.get("provenance") or {}
        actual.update(
            {
                "used_tokens": int(used.get("tokens", 0) or 0),
                "used_seconds": float(used.get("seconds", 0.0) or 0.0),
                # The reserve comparison is expressed in the same estimate units
                # as the next-call cost; the *used* figures carry their own
                # measured/provider/estimated provenance when known.
                "estimate_basis": "estimated",
                "used_tokens_source": provenance.get("tokens"),
                "used_seconds_source": provenance.get("seconds"),
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
    return {
        "calls": 0,
        "tokens": 0,
        "seconds": 0.0,
        "estimated": False,
        # Per-field provenance; ``None`` until at least one call records data.
        "provenance": {
            "tokens": None,
            "seconds": None,
            "input_tokens": None,
            "output_tokens": None,
        },
        # Number of failed attempts (never fabricated tokens/time for them).
        "failed_calls": 0,
        # Availability of the measured clock across recorded calls.
        "clock": "unavailable",
        # Transport attempts are UNKNOWN unless a caller observed them.
        "transport_attempts": None,
    }


def _accrue_split_side(
    usage: dict[str, Any],
    provenance: dict[str, Any],
    side: str,
    value: int | None,
) -> None:
    """Accrue one provider split side, keeping the aggregate honest per call.

    The per-side aggregate is a full provider total ONLY while every
    contributing call provided that side. On ANY call that did not provide the
    side, the aggregate is marked ``partial`` (retaining the sum of the known
    side) — evaluated unconditionally so a total-only call followed by a full
    call cannot present the aggregate as a complete provider split.
    """
    key = f"{side}_tokens"
    partial_key = f"{side}_tokens_partial"
    if value is None:
        usage[partial_key] = True
        provenance[f"{key}_partial"] = True
        return
    usage[key] = int(usage.get(key, 0) or 0) + int(value)
    provenance[key] = _merge_source(provenance.get(key), SOURCE_PROVIDER)


def _merge_source(existing: Any, new_source: str) -> str | None:
    """Combine per-field provenance across calls (weakest evidence wins).

    Precedence for the *combined* label: any ``estimated`` makes the total
    estimated (an aggregate that mixes measured and estimated values is not
    fully measured); otherwise a mix of ``provider``/``measured``/``missing``
    is labelled by the weakest present, so a total is never over-claimed. Note
    tokens and seconds are tracked independently.
    """
    order = [SOURCE_MEASURED, SOURCE_PROVIDER, SOURCE_MISSING, SOURCE_UNAVAILABLE, SOURCE_ESTIMATED]
    present = [s for s in (existing, new_source) if s in order]
    if not present:
        return new_source if new_source else None
    # ``estimated`` always dominates (aggregate is not fully measured).
    if SOURCE_ESTIMATED in present:
        return SOURCE_ESTIMATED
    if SOURCE_UNAVAILABLE in present:
        return SOURCE_UNAVAILABLE
    if SOURCE_MISSING in present:
        return SOURCE_MISSING
    if SOURCE_PROVIDER in present:
        return SOURCE_PROVIDER
    return SOURCE_MEASURED


def record_call_usage(
    current_usage: Mapping[str, Any] | None,
    *,
    prompt_chars: int,
    response_chars: int,
    exact_tokens: int | None = None,
    exact_seconds: float | None = None,
    char_estimator: Callable[[int], int] = estimate_tokens_from_chars,
    time_estimator: Callable[[int], float] | None = None,
    provider_usage: Mapping[str, Any] | None = None,
    measured_seconds: float | None = None,
    clock_reason: str | None = None,
    call_status: str = _CALL_STATUS_COMPLETED,
) -> dict[str, Any]:
    """Accrue one LLM call onto a run-level usage dict (JSON-safe, additive).

    This is the single place a Bull/Bear researcher records its call so the
    Debate Evaluator reads real consumption — not zeros. Call count always
    increments by one *logical* invocation (transport retries are never inferred
    here; see ``provider_usage``/``transport_attempts``).

    Token accounting (honest provenance, never fabricated):

    - A valid provider usage dict (``provider_usage`` from
      :func:`extract_provider_usage`) supplies the counts. Its provider
      ``total_tokens`` is used directly; a *conflicting* total is used only as a
      labelled ``derived``/``conflicted`` conservative total.
    - Otherwise ``exact_tokens`` (a caller-supplied exact count) is used.
    - Otherwise the character-based estimate is used and the field labelled
      ``estimated``. Unavailable components stay out of the split.

    Time accounting: a measured ``measured_seconds`` is used verbatim
    (``measured``); if it cannot be obtained the elapsed time is recorded as
    *unavailable* (``seconds`` unchanged, provenance ``unavailable``) and the
    caller is expected to abort. Character-based time is **never** revived —
    ``time_estimator``/``exact_seconds`` remain accepted for legacy callers but
    are only honoured when supplied explicitly by a non-debate caller.
    """
    usage = dict(current_usage) if current_usage else empty_usage()
    had_provenance = isinstance(usage.get("provenance"), dict)
    usage["calls"] = int(usage.get("calls", 0)) + 1
    provenance = dict(usage.get("provenance") or {})
    for key in ("tokens", "seconds", "input_tokens", "output_tokens"):
        provenance.setdefault(key, None)
    # A legacy estimated checkpoint carries ``estimated=True`` but no per-field
    # provenance. Seed the aggregate token/time provenance as ``estimated`` so a
    # later measured call produces an honest MIXED total (estimated), never a
    # fully-measured claim. Old estimated usage is never relabeled measured.
    if not had_provenance and usage.get("estimated"):
        if provenance.get("tokens") is None:
            provenance["tokens"] = SOURCE_ESTIMATED
        if provenance.get("seconds") is None:
            provenance["seconds"] = SOURCE_ESTIMATED
    total_chars = max(0, int(prompt_chars)) + max(0, int(response_chars))

    if call_status == _CALL_STATUS_FAILED:
        # A failed attempt advances the logical count but fabricates NO
        # tokens/time. Caller records the allow-listed reason separately.
        usage["failed_calls"] = int(usage.get("failed_calls", 0)) + 1
        usage["provenance"] = provenance
        return _with_legacy_estimated(usage)

    # --- Tokens ---
    token_value: int | None = None
    token_source: str | None = None
    provided_in: int | None = None
    provided_out: int | None = None
    if provider_usage is not None and provider_usage.get("available"):
        in_tok = provider_usage.get("input_tokens")
        out_tok = provider_usage.get("output_tokens")
        total_tok = provider_usage.get("total_tokens")
        provided_in = in_tok
        provided_out = out_tok
        if provider_usage.get("conflict"):
            # Provider data conflicts (sources or total vs components). Keep
            # originals, use a conservative DERIVED total, never provider-exact.
            token_value = derived_conflicted_total(provider_usage)
            token_source = "derived_conflicted"
            provenance["tokens_conflict"] = True
            # Preserve BOTH source-labelled originals per call, appending and
            # tagging with this call's index so a later conflict never overwrites
            # an earlier one.
            originals = provider_usage.get("originals")
            if isinstance(originals, (list, tuple)) and originals:
                existing = list(provenance.get("tokens_conflict_originals") or [])
                call_index = int(usage.get("calls", 0)) - 1
                for entry in originals:
                    record = dict(entry) if isinstance(entry, dict) else {"value": entry}
                    record["call_index"] = call_index
                    existing.append(record)
                provenance["tokens_conflict_originals"] = existing
        elif total_tok is not None:
            token_value = int(total_tok)
            token_source = SOURCE_PROVIDER
        elif in_tok is not None and out_tok is not None:
            token_value = int(in_tok) + int(out_tok)
            token_source = SOURCE_PROVIDER
        else:
            # Partial: exactly one of input/output present, no provider total.
            # The known side is retained; the MISSING side is estimated from the
            # matching character count (input <- prompt_chars, output <-
            # response_chars) so the call is NEVER treated as a complete exact
            # total and the estimate is not an arbitrary halving of combined length.
            if in_tok is not None:
                missing_estimate = char_estimator(max(0, int(response_chars)))
            else:
                missing_estimate = char_estimator(max(0, int(prompt_chars)))
            known = int(in_tok) if in_tok is not None else int(out_tok)
            token_value = known + missing_estimate
            token_source = SOURCE_ESTIMATED
            usage["estimated"] = True
            provenance["tokens_partial"] = True
    if token_value is None and exact_tokens is not None:
        token_value = int(exact_tokens)
        token_source = SOURCE_MEASURED
    if token_value is None:
        token_value = char_estimator(total_chars)
        token_source = SOURCE_ESTIMATED
        usage["estimated"] = True

    if token_value is not None:
        usage["tokens"] = int(usage.get("tokens", 0)) + int(token_value)
    if token_source is not None:
        prev = provenance.get("tokens")
        if prev == "derived_conflicted" or token_source == "derived_conflicted":
            provenance["tokens"] = "derived_conflicted"
        else:
            provenance["tokens"] = _merge_source(prev, token_source)

    # Split accounting: accumulate each side ONLY when this call provided it, and
    # mark a side PARTIAL on ANY call that did not provide it (even if the other
    # side was present). This is evaluated unconditionally per call, so a
    # total-only call followed by a full call correctly leaves the cumulative
    # split partial/null rather than presenting the later full call as a complete
    # provider split.
    _accrue_split_side(usage, provenance, "input", provided_in)
    _accrue_split_side(usage, provenance, "output", provided_out)

    # --- Time (measured only; never char-derived) ---
    if measured_seconds is not None:
        usage["seconds"] = float(usage.get("seconds", 0.0)) + float(measured_seconds)
        provenance["seconds"] = _merge_source(provenance.get("seconds"), SOURCE_MEASURED)
        # Clock status reflects the whole aggregate: a legacy estimated prior
        # makes the total mixed/estimated, so it is never claimed fully measured.
        if provenance.get("seconds") == SOURCE_MEASURED:
            usage["clock"] = "measured"
        else:
            usage["clock"] = "mixed"
    elif exact_seconds is not None:
        # A caller-supplied explicit seconds value (non-debate legacy caller).
        usage["seconds"] = float(usage.get("seconds", 0.0)) + float(exact_seconds)
        provenance["seconds"] = _merge_source(provenance.get("seconds"), SOURCE_MEASURED)
    else:
        provenance["seconds"] = _merge_source(provenance.get("seconds"), SOURCE_UNAVAILABLE)
        if clock_reason:
            provenance["seconds_reason"] = clock_reason
        usage["clock"] = "unavailable"

    usage["provenance"] = provenance
    return _with_legacy_estimated(usage)


def _with_legacy_estimated(usage: dict[str, Any]) -> dict[str, Any]:
    """Ensure the legacy ``estimated`` flag is set when any field is estimated."""
    provenance = usage.get("provenance") or {}
    if provenance.get("tokens") == SOURCE_ESTIMATED or provenance.get("seconds") == SOURCE_ESTIMATED:
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

    ``char_estimator`` is injected so tests use deterministic token estimates
    without touching a live provider. Elapsed time is only ever the measured
    value a caller supplies (``record_usage(exact_seconds=...)``); there is no
    character-based time fallback — a call without a measured elapsed time
    leaves ``seconds`` unchanged and marks the time provenance ``unavailable``.
    """

    def __init__(
        self,
        *,
        char_estimator: Callable[[int], int] = estimate_tokens_from_chars,
        time_estimator: Callable[[int], float] | None = None,
    ) -> None:
        self.char_estimator = char_estimator
        # Retained for backward-compatible construction by non-runtime callers.
        # It is NEVER used to derive debate runtime elapsed time: runtime calls
        # pass ``measured_seconds`` from the injectable clock, and a missing
        # clock is recorded as unavailable rather than character-estimated.
        self.time_estimator = time_estimator
        self.calls = 0
        self.tokens = 0
        self.seconds = 0.0
        self.estimated = False
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.provenance: dict[str, Any] = {
            "tokens": None,
            "seconds": None,
            "input_tokens": None,
            "output_tokens": None,
        }
        self.failed_calls = 0
        self.clock = "unavailable"

    def record_usage(
        self,
        *,
        calls: int = 1,
        prompt_chars: int = 0,
        response_chars: int = 0,
        exact_tokens: int | None = None,
        exact_seconds: float | None = None,
        provider_usage: Mapping[str, Any] | None = None,
        measured_seconds: float | None = None,
        clock_reason: str | None = None,
        call_status: str = _CALL_STATUS_COMPLETED,
        transport_attempts: int | None = None,
    ) -> None:
        """Accrue usage for one (or more) LLM calls via :func:`record_call_usage`.

        Legacy-compatible semantics for a batched ``calls=N``: the logical call
        **count** increases by ``N`` but the supplied aggregate tokens/time are
        charged **ONCE** (they describe the whole batch), not multiplied by N.
        ``transport_attempts`` is recorded only when actually observed.
        """
        count = max(0, int(calls))
        if count <= 0:
            return
        # Accrue the supplied usage once, then advance the remaining (N-1)
        # logical calls without re-charging the aggregate tokens/time.
        snapshot = record_call_usage(
            self.snapshot(),
            prompt_chars=prompt_chars,
            response_chars=response_chars,
            exact_tokens=exact_tokens,
            exact_seconds=exact_seconds,
            char_estimator=self.char_estimator,
            provider_usage=provider_usage,
            measured_seconds=measured_seconds,
            clock_reason=clock_reason,
            call_status=call_status,
        )
        self._load(snapshot)
        if count > 1:
            batched = self.snapshot()
            batched["calls"] = int(batched.get("calls", 0)) + (count - 1)
            self._load(batched)
        if transport_attempts is not None and isinstance(transport_attempts, int) and not isinstance(transport_attempts, bool):
            prev = self.transport_attempts or 0
            self.transport_attempts = prev + transport_attempts

    def _load(self, snapshot: Mapping[str, Any]) -> None:
        self.calls = int(snapshot.get("calls", 0))
        self.tokens = int(snapshot.get("tokens", 0))
        self.seconds = float(snapshot.get("seconds", 0.0))
        self.estimated = bool(snapshot.get("estimated", False))
        self.input_tokens = snapshot.get("input_tokens")
        self.output_tokens = snapshot.get("output_tokens")
        self.provenance = dict(snapshot.get("provenance") or {})
        self.failed_calls = int(snapshot.get("failed_calls", 0))
        self.clock = str(snapshot.get("clock", "unavailable"))

    @property
    def transport_attempts(self) -> int | None:
        return getattr(self, "_transport_attempts", None)

    @transport_attempts.setter
    def transport_attempts(self, value: int | None) -> None:
        self._transport_attempts = value

    def snapshot(self) -> dict[str, Any]:
        """Current usage as a JSON-safe dict (legacy keys + provenance)."""
        snapshot: dict[str, Any] = {
            "calls": self.calls,
            "tokens": self.tokens,
            "seconds": self.seconds,
            "estimated": self.estimated,
            "provenance": dict(self.provenance),
            "failed_calls": self.failed_calls,
            "clock": self.clock,
            "transport_attempts": self.transport_attempts,
        }
        if self.input_tokens is not None:
            snapshot["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            snapshot["output_tokens"] = self.output_tokens
        if self.provenance.get("input_tokens_partial"):
            snapshot["input_tokens_partial"] = True
        if self.provenance.get("output_tokens_partial"):
            snapshot["output_tokens_partial"] = True
        return snapshot
