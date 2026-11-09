"""The explicit, off-by-default switch for fundamentals-analyst tool governance.

Same allowance, same strict rules and the same section shape as the market
section (:mod:`tradingagents.graph.market_governance`), parsed by the shared
:func:`tradingagents.graph.analyst_tool_governance.parse_tool_governance`::

    "fundamentals_tool_governance": {
        "enabled": False,
        "max_rounds": 4,
        "max_calls": 8,
    }

The two sections are independent: enabling (or capping) the fundamentals
analyst never enables the market analyst, and vice versa. With the switch off
nothing here is consulted and the fundamentals analyst follows its original
path. With it on, the graph routes it through a prepare node (which saves the
registration as graph state), an execute node, and -- once the allowance is
spent -- a single, unbound wrap-up call that writes ``fundamentals_report``
from the fundamentals evidence already collected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.utils.tool_governance import ToolLimits

from .analyst_tool_governance import is_int, parse_tool_governance

#: The config key holding the section (``config["fundamentals_tool_governance"]``).
SECTION_KEY = "fundamentals_tool_governance"

#: Defaults used when the switch is on but a cap is not given. The analyst has
#: four tools and usually asks for two or three of them in one batch, so four
#: rounds / eight calls leaves room for a follow-up or two while still
#: terminating.
DEFAULT_MAX_ROUNDS = 4
DEFAULT_MAX_CALLS = 8

#: The only tools the fundamentals analyst is bound to. Governance grants this
#: exact set and nothing else (``ToolExecutor`` refuses any other name before a
#: call runs).
FUNDAMENTALS_TOOLS = (
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
)


@dataclass(frozen=True)
class FundamentalsToolGovernance:
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
                if not is_int(value) or value <= 0:
                    raise ValueError(
                        f"{SECTION_KEY}.{name} must be a positive int when "
                        f"enabled, got {value!r}"
                    )

    def limits(self) -> ToolLimits:
        """The ``ToolLimits`` for one fundamentals analyst."""
        return ToolLimits(max_rounds=self.max_rounds, max_calls=self.max_calls)


def parse_fundamentals_tool_governance(
    config: Mapping[str, Any] | None,
) -> FundamentalsToolGovernance:
    """Read and strictly validate ``config["fundamentals_tool_governance"]``.

    Absent section, or ``enabled`` absent/False -> disabled (the default).
    Unknown keys, a non-boolean ``enabled``, and ``bool``/``None``/``0``/
    negative/fractional caps are refused, never clamped.
    """
    parsed = parse_tool_governance(
        config,
        SECTION_KEY,
        default_max_rounds=DEFAULT_MAX_ROUNDS,
        default_max_calls=DEFAULT_MAX_CALLS,
    )
    return FundamentalsToolGovernance(
        enabled=parsed.enabled,
        max_rounds=parsed.max_rounds,
        max_calls=parsed.max_calls,
    )


def is_enabled(config: Mapping[str, Any] | None) -> bool:
    """Whether fundamentals tool governance is switched on for this run."""
    return parse_fundamentals_tool_governance(config).enabled


__all__ = [
    "DEFAULT_MAX_CALLS",
    "DEFAULT_MAX_ROUNDS",
    "FUNDAMENTALS_TOOLS",
    "FundamentalsToolGovernance",
    "SECTION_KEY",
    "is_enabled",
    "parse_fundamentals_tool_governance",
]
