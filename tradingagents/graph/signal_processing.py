"""Extract the 5-tier portfolio rating from the Portfolio Manager's decision.

The Portfolio Manager produces a typed ``PortfolioDecision`` via structured
output and renders it to markdown that always carries a ``**Rating**: X``
header (see :func:`tradingagents.agents.schemas.render_pm_decision`).  The
deterministic heuristic in :mod:`tradingagents.agents.utils.rating` is more
than sufficient to extract that rating; no extra LLM call is needed.

This module exists for backwards compatibility with callers that expect a
``SignalProcessor.process_signal(text)`` interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tradingagents.agents.utils.output_guard import HOLD, is_blocked_run
from tradingagents.agents.utils.rating import RATING_REVIEW, extract_rating


class SignalProcessor:
    """Read the 5-tier rating out of a Portfolio Manager decision."""

    def __init__(self, quick_thinking_llm: Any = None):
        # The LLM argument is accepted for backwards compatibility but ignored:
        # the PM's structured output guarantees the rating is parseable from the
        # rendered markdown without a second LLM call, so it is not stored.
        pass

    def process_signal(self, full_signal: str, state: Mapping[str, Any] | None = None) -> str:
        """Return one of Buy / Overweight / Hold / Underweight / Sell, or REVIEW.

        When the structured gate ``state`` proves the run is blocked, the
        authoritative final signal is ``Hold`` regardless of what text the model
        produced. This is the structured enforcement at the signal boundary: even
        if a decision-header format the guard did not anticipate slips through as
        text, a blocked run can never end as a directional call.

        Otherwise an unrecognizable decision yields ``REVIEW`` rather than a
        fabricated ``Hold``, so a parsing failure is visible instead of
        masquerading as a tradeable neutral signal (#1170). Consumers that map
        the result onto the 5-tier enum should guard with
        :func:`~tradingagents.agents.utils.rating.is_review`.
        """
        if state is not None and is_blocked_run(state):
            return HOLD
        rating = extract_rating(full_signal)
        return rating if rating is not None else RATING_REVIEW
