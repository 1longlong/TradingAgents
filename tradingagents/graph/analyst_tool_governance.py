"""The strict, shared shape of one analyst's opt-in tool-governance section.

An *analyst tool allowance*: how many ``model -> tools -> model`` rounds one
analyst may cycle through and how many calls it may actually run
(``tradingagents.agents.utils.tool_governance``). It is not a run-level budget
and it never counts HTTP requests or vendor attempts -- those stay owned by the
routing layer (``dataflows.retry_session`` / ``dataflows.vendor_breaker``).

Each analyst has its own section, parsed by the same rules::

    "market_tool_governance":       {"enabled": False, ...}
    "fundamentals_tool_governance": {"enabled": False, ...}

The rules, identical for every section (see :func:`parse_tool_governance`):

* an absent section, or ``enabled`` absent/False -> disabled (the default);
* ``enabled`` must be a real ``bool`` (``"yes"``/``1`` are refused);
* only the keys ``enabled``/``max_rounds``/``max_calls`` are accepted -- an
  unknown key is refused, never ignored;
* when enabled both caps must be **finite positive ints**: ``bool``, ``None``,
  ``0``, a negative number and a fractional value are all refused (``None``
  under the positive-int contract would mean "no cap", and governance that
  cannot stop is not governance). Only *omitting* a cap uses its default;
* while disabled the caps are not consulted, but a nonsensical value left in
  the file is still refused loudly; ``None`` there is the "not set" marker.

The two analysts are configured and switched independently: enabling one never
enables the other, and the default section of one is never read for the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.utils.tool_governance import ToolLimits

_ALLOWED_KEYS = frozenset({"enabled", "max_rounds", "max_calls"})


def is_int(value: Any) -> bool:
    """A real int, never a ``bool`` (which is an ``int`` subclass)."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class AnalystToolGovernance:
    """The validated switch and its two caps for one analyst section.

    When ``enabled`` is true both caps are positive ints (never ``None``): the
    section cannot switch governance on without a finite limit. When it is
    false both are ``None`` and never consulted.
    """

    section: str
    enabled: bool = False
    max_rounds: int | None = None
    max_calls: int | None = None

    def __post_init__(self) -> None:
        if self.enabled:
            for name in ("max_rounds", "max_calls"):
                value = getattr(self, name)
                if not is_int(value) or value <= 0:
                    raise ValueError(
                        f"{self.section}.{name} must be a positive int when "
                        f"enabled, got {value!r}"
                    )

    def limits(self) -> ToolLimits:
        """The ``ToolLimits`` for this analyst (caps its two counters)."""
        return ToolLimits(max_rounds=self.max_rounds, max_calls=self.max_calls)


def _check_cap(section_key: str, name: str, value: Any) -> int:
    if not is_int(value) or value <= 0:
        raise ValueError(
            f"{section_key}.{name} must be a positive int, got {value!r}"
        )
    return value


def parse_tool_governance(
    config: Mapping[str, Any] | None,
    section_key: str,
    *,
    default_max_rounds: int,
    default_max_calls: int,
) -> AnalystToolGovernance:
    """Read and strictly validate ``config[section_key]``.

    Absent section, or ``enabled`` absent/False -> disabled (the default).

    When enabled, both caps must be **finite**: the section always yields a
    positive int for each one. Only *omitting* the key uses the section's
    default; an explicit value must be a positive int, and an explicit ``None``
    is refused, because under the positive-int contract it means "no cap" --
    governance that cannot stop is not governance. A user who wants the
    defaults leaves the keys out.
    """
    section = (config or {}).get(section_key)
    if section is None:
        return AnalystToolGovernance(section=section_key)
    if not isinstance(section, Mapping):
        raise ValueError(f"{section_key} must be a mapping, got {section!r}")
    unknown = sorted(set(section) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(
            f"unknown {section_key} key(s): {', '.join(unknown)}"
        )
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(
            f"{section_key}.enabled must be a boolean, got {enabled!r}"
        )
    if not enabled:
        # Disabled: caps are irrelevant and never read, but a nonsensical value
        # left in the file is still worth refusing loudly. ``None`` here is the
        # "not set" marker, not an unbounded cap.
        if section.get("max_rounds") is not None:
            _check_cap(section_key, "max_rounds", section["max_rounds"])
        if section.get("max_calls") is not None:
            _check_cap(section_key, "max_calls", section["max_calls"])
        return AnalystToolGovernance(section=section_key, enabled=False)
    return AnalystToolGovernance(
        section=section_key,
        enabled=True,
        max_rounds=_check_cap(
            section_key, "max_rounds", section.get("max_rounds", default_max_rounds)
        ),
        max_calls=_check_cap(
            section_key, "max_calls", section.get("max_calls", default_max_calls)
        ),
    )


__all__ = ["AnalystToolGovernance", "is_int", "parse_tool_governance"]
