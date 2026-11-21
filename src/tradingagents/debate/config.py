"""``debate_termination`` configuration group for Phase 3B dynamic termination.

The group carries safe backward-compatible defaults and an explicit
:meth:`DebateTerminationConfig.validate` that checks types, ranges, and
cross-constraints so a misconfiguration fails clearly before graph execution
rather than silently falling back.

The ``enabled`` flag provides a fixed-round baseline mode for comparison: when
``False``, the Debate Evaluator reproduces the legacy fixed-``max_debate_rounds``
routing and does not apply dynamic rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DEFAULT_LIMITS = 2_000_000
_DEFAULT_TIME = 600.0
_DEFAULT_SUMMARY_TOKENS = 4_000
_DEFAULT_SUMMARY_SECONDS = 90.0


@dataclass(frozen=True)
class DebateTerminationConfig:
    """Tunable knobs for dynamic debate termination.

    All scalar fields are validated by :meth:`validate`; the dataclass is frozen
    so a validated instance cannot diverge afterward.
    """

    enabled: bool = True
    no_new_evidence_patience: int = 1
    stance_distance_threshold: float = 1.0
    confidence_delta_threshold: float = 0.25
    max_calls: int = _DEFAULT_LIMITS
    max_tokens: int = _DEFAULT_LIMITS
    max_time: float = _DEFAULT_TIME
    reserved_summary_tokens: int = _DEFAULT_SUMMARY_TOKENS
    reserved_summary_seconds: float = _DEFAULT_SUMMARY_SECONDS
    next_round_estimate_tokens: int = 2_000
    next_round_estimate_seconds: float = 60.0
    max_debate_rounds: int = 1
    evidence_manifest_field: str = "data_quality_evidence_records"
    trace_field: str = "debate_termination_decision"

    def validate(self) -> None:
        """Validate types, ranges, and cross-constraints; raise ``ValueError``.

        Raised before graph execution so a bad ``debate_termination`` block is
        reported explicitly instead of silently degrading to a default.
        """
        if not isinstance(self.enabled, bool):
            raise ValueError("debate_termination.enabled must be a bool")
        if not isinstance(self.no_new_evidence_patience, int) or isinstance(
            self.no_new_evidence_patience, bool
        ):
            raise ValueError("debate_termination.no_new_evidence_patience must be an int")
        if self.no_new_evidence_patience < 1:
            raise ValueError(
                "debate_termination.no_new_evidence_patience must be >= 1 "
                "(a per-round automatic stop threshold)"
            )
        if not isinstance(self.stance_distance_threshold, (int, float)) or isinstance(
            self.stance_distance_threshold, bool
        ):
            raise ValueError("debate_termination.stance_distance_threshold must be a number")
        if not 0 <= self.stance_distance_threshold <= 4:
            raise ValueError(
                "debate_termination.stance_distance_threshold must be in [0, 4] "
                "(the stance scale spans -2..2)"
            )
        if not isinstance(self.confidence_delta_threshold, (int, float)) or isinstance(
            self.confidence_delta_threshold, bool
        ):
            raise ValueError("debate_termination.confidence_delta_threshold must be a number")
        if not 0 <= self.confidence_delta_threshold <= 1:
            raise ValueError(
                "debate_termination.confidence_delta_threshold must be in [0, 1]"
            )

        for name in ("max_calls", "max_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"debate_termination.{name} must be a positive int")
        if not isinstance(self.max_time, (int, float)) or isinstance(self.max_time, bool):
            raise ValueError("debate_termination.max_time must be a number")
        if not self.max_time > 0:
            raise ValueError("debate_termination.max_time must be positive")

        for name in ("reserved_summary_tokens", "next_round_estimate_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"debate_termination.{name} must be a non-negative int")
        for name in ("reserved_summary_seconds", "next_round_estimate_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"debate_termination.{name} must be non-negative")

        if not isinstance(self.max_debate_rounds, int) or isinstance(
            self.max_debate_rounds, bool
        ) or self.max_debate_rounds < 1:
            raise ValueError("debate_termination.max_debate_rounds must be a positive int")

        # Cross-constraint: the summary reserve must not consume the whole budget.
        if self.reserved_summary_tokens >= self.max_tokens:
            raise ValueError(
                "debate_termination.reserved_summary_tokens must be less than "
                "max_tokens so the manager can always conclude"
            )
        if self.reserved_summary_seconds >= self.max_time:
            raise ValueError(
                "debate_termination.reserved_summary_seconds must be less than "
                "max_time so the manager can always conclude"
            )
        if not isinstance(self.evidence_manifest_field, str) or not self.evidence_manifest_field:
            raise ValueError("debate_termination.evidence_manifest_field must be a non-empty str")
        if not isinstance(self.trace_field, str) or not self.trace_field:
            raise ValueError("debate_termination.trace_field must be a non-empty str")

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DebateTerminationConfig:
        """Build a config from a plain dict, falling back to defaults per key.

        Unknown keys (or a non-dict ``data``) raise ``ValueError`` so a
        misspelled or drifting config key fails clearly instead of being
        silently dropped. The resulting instance is validated before being
        returned.
        """
        data = data or {}
        cls._reject_unknown_keys(data)
        known = {
            field_name: data.get(field_name, default)
            for field_name, default in cls._defaults().items()
        }
        instance = cls(**known)
        instance.validate()
        return instance

    @classmethod
    def _reject_unknown_keys(cls, data: dict[str, Any]) -> None:
        """Raise ``ValueError`` on any key not in the authoritative field set."""
        if not isinstance(data, dict):
            raise ValueError(
                "debate_termination config must be a dict mapping, got "
                f"{type(data).__name__}"
            )
        known = set(cls._defaults().keys())
        unknown = sorted(set(data.keys()) - known)
        if unknown:
            raise ValueError(
                "debate_termination config has unknown key(s): "
                + ", ".join(unknown)
                + f". Known keys: {', '.join(sorted(known))}"
            )

    @classmethod
    def _defaults(cls) -> dict[str, Any]:
        # ``max_debate_rounds`` defaults to the legacy
        # ``DEFAULT_CONFIG["max_debate_rounds"]`` (1) so an absent group and an
        # absent top-level key both reproduce the baseline round count.
        return {
            "enabled": True,
            "no_new_evidence_patience": 1,
            "stance_distance_threshold": 1.0,
            "confidence_delta_threshold": 0.25,
            "max_calls": _DEFAULT_LIMITS,
            "max_tokens": _DEFAULT_LIMITS,
            "max_time": _DEFAULT_TIME,
            "reserved_summary_tokens": _DEFAULT_SUMMARY_TOKENS,
            "reserved_summary_seconds": _DEFAULT_SUMMARY_SECONDS,
            "next_round_estimate_tokens": 2_000,
            "next_round_estimate_seconds": 60.0,
            "max_debate_rounds": 1,
            "evidence_manifest_field": "data_quality_evidence_records",
            "trace_field": "debate_termination_decision",
        }

    def to_root_config(self) -> dict[str, Any]:
        """The ``max_debate_rounds`` value, read both here and as a top-level key.

        Kept for callers that want the single authoritative cap value.
        """
        return {"max_debate_rounds": self.max_debate_rounds}


def resolve_debate_termination_config(root_config: dict[str, Any] | None) -> DebateTerminationConfig:
    """Resolve the ``debate_termination`` group from a root config dict.

    The group is read from ``root_config["debate_termination"]`` (a dict). If
    absent, defaults are used. ``max_debate_rounds`` in the group, when set,
    takes precedence over the legacy top-level key so there is one authoritative
    cap; otherwise the legacy top-level default (1) is preserved for
    compatibility.
    """
    root_config = root_config or {}
    raw_group = root_config.get("debate_termination")
    defaults = DebateTerminationConfig._defaults()
    if isinstance(raw_group, dict):
        DebateTerminationConfig._reject_unknown_keys(raw_group)
        merged = dict(defaults)
        merged.update(raw_group)
    elif raw_group is None:
        merged = dict(defaults)
    else:
        raise ValueError(
            "debate_termination must be a dict mapping, got "
            f"{type(raw_group).__name__}"
        )
    # Back-compat: a legacy top-level ``max_debate_rounds`` is the authoritative
    # cap whenever the ``debate_termination`` group does not state its own, so a
    # config that only sets the legacy key keeps its exact meaning.
    group_set_cap = isinstance(raw_group, dict) and "max_debate_rounds" in raw_group
    if not group_set_cap:
        legacy = root_config.get("max_debate_rounds")
        if legacy is not None:
            merged["max_debate_rounds"] = legacy
    instance = DebateTerminationConfig(**merged)
    instance.validate()
    return instance


DEFAULT_DEBATE_TERMINATION_CONFIG = DebateTerminationConfig.from_dict(None)
