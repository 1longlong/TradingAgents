"""The explicit, off-by-default switch for market-analyst tool governance.

This is an *analyst tool allowance*: how many ``model -> tools -> model`` rounds
the market analyst may cycle through and how many calls it may actually run
(``tradingagents.agents.utils.tool_governance``). It is not a run-level budget
and it never counts HTTP requests or vendor attempts -- those stay owned by the
routing layer (``dataflows.retry_session`` / ``dataflows.vendor_breaker``).

With the switch off (the default), nothing here is consulted and the market
analyst follows exactly the path it always has. With it on, the graph routes the
market analyst through a prepare node (which saves the registration as graph
state), an execute node, and -- once the allowance is spent -- a single wrap-up
node that writes ``market_report`` from the evidence already collected.

The section is a small, flat dict so it can be validated on its own::

    "market_tool_governance": {
        "enabled": False,
        "max_rounds": 3,
        "max_calls": 8,
    }

Every value is checked strictly; an unknown key, a misspelled boolean, a
negative or fractional cap -- or an explicit ``None`` cap while enabled -- is
refused rather than clamped, in the same spirit as the rest of
``default_config``. Omit a cap to use its default; you cannot switch governance
on without a finite limit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.utils.tool_governance import ToolLimits

#: The config key holding the section (``config["market_tool_governance"]``).
SECTION_KEY = "market_tool_governance"

_ALLOWED_KEYS = frozenset({"enabled", "max_rounds", "max_calls"})

#: Defaults used when the switch is on but a cap is not given. Deliberately
#: generous enough for a normal market analysis (get_stock_data, a handful of
#: indicators, the verified snapshot) while still terminating.
DEFAULT_MAX_ROUNDS = 4
DEFAULT_MAX_CALLS = 10


@dataclass(frozen=True)
class MarketToolGovernance:
    """The validated switch and its two caps.

    When ``enabled`` is true both caps are positive ints (never ``None``): the
    section cannot switch governance on without a finite limit. When it is
    false both are ``None`` and never consulted.
    """

    enabled: bool = False
    max_rounds: int | None = None
    max_calls: int | None = None

    def __post_init__(self) -> None:
        if self.enabled:
            for name in ("max_rounds", "max_calls"):
                value = getattr(self, name)
                if not _is_int(value) or value <= 0:
                    raise ValueError(
                        f"{SECTION_KEY}.{name} must be a positive int when "
                        f"enabled, got {value!r}"
                    )

    def limits(self) -> ToolLimits:
        """The ``ToolLimits`` for one market analyst (caps the two counters)."""
        return ToolLimits(max_rounds=self.max_rounds, max_calls=self.max_calls)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_cap(name: str, value: Any) -> int:
    if not _is_int(value) or value <= 0:
        raise ValueError(
            f"{SECTION_KEY}.{name} must be a positive int, got {value!r}"
        )
    return value


def parse_market_tool_governance(
    config: Mapping[str, Any] | None,
) -> MarketToolGovernance:
    """Read and strictly validate ``config["market_tool_governance"]``.

    Absent section, or ``enabled`` absent/False -> disabled (the default).

    When enabled, both caps must be **finite**: the section always yields a
    positive int for each one. Only *omitting* the key uses
    :data:`DEFAULT_MAX_ROUNDS` / :data:`DEFAULT_MAX_CALLS`; an explicit value
    must be a positive int, and an explicit ``None`` is refused, because under
    the positive-int contract it means "no cap" -- governance that cannot stop
    is not governance. A user who wants the defaults leaves the keys out.
    """
    section = (config or {}).get(SECTION_KEY)
    if section is None:
        return MarketToolGovernance()
    if not isinstance(section, Mapping):
        raise ValueError(f"{SECTION_KEY} must be a mapping, got {section!r}")
    unknown = sorted(set(section) - _ALLOWED_KEYS)
    if unknown:
        raise ValueError(
            f"unknown {SECTION_KEY} key(s): {', '.join(unknown)}"
        )
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(
            f"{SECTION_KEY}.enabled must be a boolean, got {enabled!r}"
        )
    if not enabled:
        # Disabled: caps are irrelevant and never read, but a nonsensical value
        # left in the file is still worth refusing loudly. ``None`` here is the
        # "not set" marker, not an unbounded cap.
        if section.get("max_rounds") is not None:
            _check_cap("max_rounds", section["max_rounds"])
        if section.get("max_calls") is not None:
            _check_cap("max_calls", section["max_calls"])
        return MarketToolGovernance(enabled=False)
    return MarketToolGovernance(
        enabled=True,
        max_rounds=_check_cap("max_rounds", section.get("max_rounds", DEFAULT_MAX_ROUNDS)),
        max_calls=_check_cap("max_calls", section.get("max_calls", DEFAULT_MAX_CALLS)),
    )


def is_enabled(config: Mapping[str, Any] | None) -> bool:
    """Whether market tool governance is switched on for this run."""
    return parse_market_tool_governance(config).enabled
