"""The spend gate described in ``BUDGET_GUARD_DESIGN.md``.

The design document specified four states and four quantities; before this
module none of them existed in code, so the document described a guard that
could not be inspected, executed or falsified (audit C-04). A spec that reads as
implemented while nothing implements it is worse than an absent spec, because it
invites the reader to trust a check that is not there.

This round is ``UNCAPPED``: ``max_total_tokens`` is ``null`` by design, and the
gate never blocks. Its job is *reporting*: to say plainly what is known about
spend and, crucially, to refuse to claim a total when provider usage is missing.

States
------
``UNCAPPED``
    No cap configured. Spend is still reported; :meth:`BudgetGate.check` never
    blocks.
``OK``
    A cap is configured and known spend is below it.
``EXHAUSTED``
    A cap is configured and known spend has reached it. Further paid calls are
    refused.
``UNKNOWN_SPEND``
    At least one call reported no usage, so ``used`` is a lower bound rather
    than a total. Reported truthfully; never rounded to zero.

``UNCAPABLE`` is not a gate state: it is the reason a gate cannot be built at
all (a negative or non-integer cap), and raises at construction.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

OK = "OK"
UNCAPPED = "UNCAPPED"
EXHAUSTED = "EXHAUSTED"
UNKNOWN_SPEND = "UNKNOWN_SPEND"

#: Every state the gate can report.
STATES = (OK, UNCAPPED, EXHAUSTED, UNKNOWN_SPEND)


class BudgetConfigError(ValueError):
    """A cap that cannot be interpreted. Never silently replaced by a default."""


@dataclass
class BudgetGate:
    """Accumulate observed usage and answer whether more spend may proceed.

    ``max_total_tokens=None`` means uncapped. Anything else must be a
    non-negative integer; a null cap is *not* replaced by a fallback, because a
    silent default would change what the experiment measures and make a capped
    run look comparable to an uncapped one.
    """

    max_total_tokens: int | None = None
    used: int = 0
    reserved: int = 0
    #: Calls whose usage payload was absent or partial. Non-zero => lower bound.
    unmeasured_calls: int = 0
    _seen_run_ids: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        cap = self.max_total_tokens
        if cap is None:
            return
        if isinstance(cap, bool) or not isinstance(cap, int):
            raise BudgetConfigError(
                f"max_total_tokens must be null or an int, got {type(cap).__name__}"
            )
        if cap < 0:
            raise BudgetConfigError(f"max_total_tokens must be >= 0, got {cap}")

    # -- recording ---------------------------------------------------------

    def record_call(
        self,
        run_id: str,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        reported: bool,
    ) -> None:
        """Record one deduplicated call.

        ``run_id`` identifies one LangChain call; a duplicate delivery for the
        same id is dropped, so ``used`` counts each call exactly once by
        structure rather than by arithmetic luck. ``reported=False`` (or a
        missing field) makes spend a lower bound instead of adding a zero.
        """
        if run_id in self._seen_run_ids:
            return
        self._seen_run_ids.add(run_id)
        if not reported or input_tokens is None or output_tokens is None:
            self.unmeasured_calls += 1
            # A partial payload's known half is still spend we observed; count
            # what was reported and remember that the total is a lower bound.
            self.used += (input_tokens or 0) + (output_tokens or 0)
        else:
            self.used += input_tokens + output_tokens

    def record_calls(self, calls: Iterable[dict]) -> None:
        """Record a sequence of ``{"run_id", "input", "output", "reported"}``."""
        for call in calls:
            self.record_call(
                call["run_id"],
                input_tokens=call.get("input"),
                output_tokens=call.get("output"),
                reported=call.get("reported", True),
            )

    # -- reporting ---------------------------------------------------------

    @property
    def capped(self) -> bool:
        return self.max_total_tokens is not None

    @property
    def remaining(self) -> int | None:
        """``cap - used - reserved``, or ``None`` when uncapped.

        When spend is a lower bound the remaining figure is an *upper* bound on
        what is left; :meth:`describe` says so rather than implying headroom.
        """
        if self.max_total_tokens is None:
            return None
        return self.max_total_tokens - self.used - self.reserved

    @property
    def state(self) -> str:
        # A cap that is already provably blown is exhausted whatever the
        # unmeasured calls would add: ``used`` alone has reached it, so the
        # lower bound is enough to refuse. Testing UNKNOWN_SPEND first made
        # ``used=999_999`` with a cap of 100 report UNKNOWN_SPEND and *not*
        # block, which is the one case the gate exists for (audit C-04r).
        if (self.capped and self.max_total_tokens is not None
                and self.used + self.reserved >= self.max_total_tokens):
            return EXHAUSTED
        if self.unmeasured_calls:
            # Unknown spend still outranks a *satisfied-looking* cap: it may not
            # be satisfied, and saying OK would be a claim the data does not
            # support.
            return UNKNOWN_SPEND
        if not self.capped:
            return UNCAPPED
        return OK

    def check(self) -> str:
        """Return the state, raising only when a known-exhausted cap is hit."""
        state = self.state
        if state == EXHAUSTED:
            raise BudgetExhausted(
                f"spend {self.used} (+{self.reserved} reserved) has reached the "
                f"cap {self.max_total_tokens}; refusing further paid calls"
            )
        return state

    def describe(self) -> dict:
        """A report-ready summary that never presents a lower bound as a total."""
        state = self.state
        return {
            "state": state,
            "max_total_tokens": self.max_total_tokens,
            "used_tokens": self.used,
            "used_is_lower_bound": state == UNKNOWN_SPEND,
            "unmeasured_calls": self.unmeasured_calls,
            "reserved_tokens": self.reserved,
            "remaining_tokens": self.remaining,
            "remaining_is_upper_bound": state == UNKNOWN_SPEND,
            "blocks_run": state == EXHAUSTED,
        }


class BudgetExhausted(RuntimeError):
    """A capped run has consumed its budget; further paid calls are refused."""
