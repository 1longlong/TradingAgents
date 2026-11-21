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

Every value is checked strictly (see
:mod:`tradingagents.graph.analyst_tool_governance`): an unknown key, a
misspelled boolean, a negative or fractional cap -- or an explicit ``None`` cap
while enabled -- is refused rather than clamped, in the same spirit as the rest
of ``default_config``. Omit a cap to use its default; you cannot switch
governance on without a finite limit. The market and fundamentals sections are
independent: each is enabled and capped on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.utils.tool_governance import ToolLimits

from .analyst_tool_governance import is_int, parse_tool_governance

#: The config key holding the section (``config["market_tool_governance"]``).
SECTION_KEY = "market_tool_governance"

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
                if not is_int(value) or value <= 0:
                    raise ValueError(
                        f"{SECTION_KEY}.{name} must be a positive int when "
                        f"enabled, got {value!r}"
                    )

    def limits(self) -> ToolLimits:
        """The ``ToolLimits`` for one market analyst (caps the two counters)."""
        return ToolLimits(max_rounds=self.max_rounds, max_calls=self.max_calls)


def parse_market_tool_governance(
    config: Mapping[str, Any] | None,
) -> MarketToolGovernance:
    """Read and strictly validate ``config["market_tool_governance"]``.

    Absent section, or ``enabled`` absent/False -> disabled (the default). See
    :func:`tradingagents.graph.analyst_tool_governance.parse_tool_governance`
    for the exact rules shared with the fundamentals section.
    """
    parsed = parse_tool_governance(
        config,
        SECTION_KEY,
        default_max_rounds=DEFAULT_MAX_ROUNDS,
        default_max_calls=DEFAULT_MAX_CALLS,
    )
    return MarketToolGovernance(
        enabled=parsed.enabled,
        max_rounds=parsed.max_rounds,
        max_calls=parsed.max_calls,
    )


def is_enabled(config: Mapping[str, Any] | None) -> bool:
    """Whether market tool governance is switched on for this run."""
    return parse_market_tool_governance(config).enabled
