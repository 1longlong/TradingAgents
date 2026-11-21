"""REQ-WEB-001/013, FR-DDT-004, ADR-001/007: adapt existing core policy only."""

from __future__ import annotations

import math
import os
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from tradingagents.debate.config import resolve_debate_termination_config
from tradingagents.default_config import _apply_env_overrides
from tradingagents_web.models.requests import DebatePolicyRequest

PUBLIC_DEBATE_FIELDS = (
    "enabled",
    "max_debate_rounds",
    "no_new_evidence_patience",
    "stance_distance_threshold",
    "confidence_delta_threshold",
    "max_calls",
    "max_tokens",
    "max_time",
    "reserved_summary_tokens",
    "reserved_summary_seconds",
    "next_round_estimate_tokens",
    "next_round_estimate_seconds",
)


def configure_debate_policy(
    config: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
    legacy_depth: int | None = None,
    risk_rounds: int | None = None,
) -> dict[str, Any]:
    """Merge per-run public inputs; the core validates the effective policy."""
    result = deepcopy(config)
    group = result.get("debate_termination")
    if group is not None and not isinstance(group, dict):
        raise ValueError("debate_termination must be a configuration object")
    group = dict(group or {})
    if overrides is not None:
        if set(overrides) - set(PUBLIC_DEBATE_FIELDS):
            raise ValueError("unsupported public debate setting")
        if any(value is None for value in overrides.values()):
            raise ValueError("debate settings must not be null")
    if legacy_depth is not None:
        group["max_debate_rounds"] = legacy_depth
        result["max_debate_rounds"] = legacy_depth
        result["max_risk_discuss_rounds"] = legacy_depth
    group.update(overrides or {})
    if risk_rounds is not None:
        result["max_risk_discuss_rounds"] = risk_rounds
    _apply_env_overrides(result)
    if os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS"):
        group["max_debate_rounds"] = result["max_debate_rounds"]
    result["debate_termination"] = group
    policy = resolve_debate_termination_config(result)
    normalized = asdict(policy)
    if any(isinstance(value, float) and not math.isfinite(value) for value in normalized.values()):
        raise ValueError("debate settings must use finite numbers")
    risk = result.get("max_risk_discuss_rounds", 1)
    if isinstance(risk, bool) or not isinstance(risk, int) or risk < 1:
        raise ValueError("max_risk_discuss_rounds must be a positive integer")
    result["debate_termination"] = normalized
    result["max_debate_rounds"] = policy.max_debate_rounds
    result["max_risk_discuss_rounds"] = risk
    return result


def public_debate_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Project normalized scalar controls, excluding core state/path selectors."""
    policy = asdict(resolve_debate_termination_config(config))
    return {key: policy[key] for key in PUBLIC_DEBATE_FIELDS}


def recorded_debate_policy(value: Any) -> dict[str, Any] | None:
    """Read-only history projection: missing/invalid policy remains unknown."""
    if not isinstance(value, dict) or set(value) != set(PUBLIC_DEBATE_FIELDS):
        return None
    try:
        parsed = DebatePolicyRequest.model_validate(value).model_dump()
        if any(item is None for item in parsed.values()):
            return None
        return public_debate_policy({"debate_termination": parsed})
    except (ValueError, TypeError):
        return None
