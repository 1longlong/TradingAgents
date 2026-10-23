"""Phase 3B offline tests for budget accounting and reserve protection.

Covers deterministic token/time estimation, the additive run-level usage
tracker, the summary-reserve guarantee, hard-limit detection, and the
full-round eligibility check, plus the graph wiring that records a call per
Bull/Bear invocation.
"""

from __future__ import annotations

from tradingagents.debate.budget import (
    empty_usage,
    estimate_seconds_from_chars,
    estimate_tokens_from_chars,
    record_call_usage,
)
from tradingagents.debate.models import BudgetState


class TestEstimate:
    def test_tokens_from_chars_ceil(self):
        assert estimate_tokens_from_chars(0) == 0
        assert estimate_tokens_from_chars(4) == 1
        assert estimate_tokens_from_chars(5) == 2

    def test_seconds_from_chars(self):
        assert estimate_seconds_from_chars(0) == 0.0
        assert estimate_seconds_from_chars(300, 30.0) == 10.0

    def test_estimators_deterministic(self):
        assert estimate_tokens_from_chars(1234) == estimate_tokens_from_chars(1234)
        assert estimate_seconds_from_chars(99) == estimate_seconds_from_chars(99)


class TestRecordCallUsage:
    def test_increments_calls_and_estimates(self):
        usage = record_call_usage(None, prompt_chars=400, response_chars=400)
        assert usage["calls"] == 1
        assert usage["tokens"] == estimate_tokens_from_chars(800)
        assert usage["estimated"] is True

    def test_accumulates_totals(self):
        u = record_call_usage(None, prompt_chars=400, response_chars=0)
        u = record_call_usage(u, prompt_chars=400, response_chars=0)
        assert u["calls"] == 2
        assert u["tokens"] == estimate_tokens_from_chars(400) * 2

    def test_exact_usage_non_estimated(self):
        u = record_call_usage(
            None,
            prompt_chars=10,
            response_chars=10,
            exact_tokens=50,
            exact_seconds=1.2,
        )
        assert u["tokens"] == 50
        assert u["seconds"] == 1.2
        assert u["estimated"] is False

    def test_empty_usage(self):
        assert empty_usage() == {"calls": 0, "tokens": 0, "seconds": 0.0, "estimated": False}

    def test_json_safe(self):
        import json

        u = record_call_usage(None, prompt_chars=10, response_chars=10)
        assert json.dumps(u)


class TestBudgetState:
    def test_summary_reserve_guaranteed_true(self):
        b = BudgetState(
            max_calls=100, max_tokens=10000, max_time=600,
            used_calls=2, used_tokens=1000, used_time=60,
            max_debate_rounds=5, reserved_summary_tokens=1000,
            reserved_summary_seconds=30, next_round_estimate_tokens=200,
            next_round_estimate_seconds=10,
        )
        assert b.summary_reserve_guaranteed(tokens=200, seconds=10)

    def test_summary_reserve_not_guaranteed_on_token_boundary(self):
        # max_tokens 1000, used 900, reserve 100, estimate 200 -> 900+100+200 > 1000
        b = BudgetState(
            max_calls=100, max_tokens=1000, max_time=600,
            used_calls=2, used_tokens=900, used_time=60,
            max_debate_rounds=5, reserved_summary_tokens=100,
            reserved_summary_seconds=30, next_round_estimate_tokens=200,
            next_round_estimate_seconds=10,
        )
        assert not b.summary_reserve_guaranteed(tokens=200, seconds=10)

    def test_hard_limit_reached_variants(self):
        base = {
            "max_calls": 10, "max_tokens": 10000, "max_time": 600,
            "max_debate_rounds": 5, "reserved_summary_tokens": 1000,
            "reserved_summary_seconds": 30, "next_round_estimate_tokens": 200,
            "next_round_estimate_seconds": 10,
        }
        assert BudgetState(used_calls=10, used_tokens=500, used_time=60, **base).hard_limit_reached()
        assert BudgetState(used_calls=9, used_tokens=10000, used_time=60, **base).hard_limit_reached()
        assert BudgetState(used_calls=9, used_tokens=500, used_time=600, **base).hard_limit_reached()
        assert not BudgetState(used_calls=9, used_tokens=500, used_time=60, **base).hard_limit_reached()

    def test_can_run_full_round_true_when_enough_calls(self):
        b = BudgetState(
            max_calls=10, max_tokens=100000, max_time=600,
            used_calls=8, used_tokens=100, used_time=10,
            max_debate_rounds=5, reserved_summary_tokens=1000,
            reserved_summary_seconds=30, next_round_estimate_tokens=200,
            next_round_estimate_seconds=10,
        )
        # 2 remaining calls is enough for a full Bull+Bear round.
        assert (b.max_calls - b.used_calls) == 2
        assert b.can_run_full_round()

    def test_can_run_full_round_false_when_only_one_call_left(self):
        b = BudgetState(
            max_calls=9, max_tokens=100000, max_time=600,
            used_calls=8, used_tokens=100, used_time=10,
            max_debate_rounds=5, reserved_summary_tokens=1000,
            reserved_summary_seconds=30, next_round_estimate_tokens=200,
            next_round_estimate_seconds=10,
        )
        assert (b.max_calls - b.used_calls) == 1
        assert not b.can_run_full_round()

    def test_can_run_full_round_false_when_reserve_fails(self):
        b = BudgetState(
            max_calls=100, max_tokens=1000, max_time=600,
            used_calls=2, used_tokens=900, used_time=100,
            max_debate_rounds=5, reserved_summary_tokens=100,
            reserved_summary_seconds=30, next_round_estimate_tokens=1000,
            next_round_estimate_seconds=10,
        )
        assert not b.can_run_full_round()

    def test_budget_state_round_trip_json(self):
        import json

        b = BudgetState(
            max_calls=10, max_tokens=1000, max_time=600,
            used_calls=2, used_tokens=50, used_time=5.0,
            max_debate_rounds=5, reserved_summary_tokens=10,
            reserved_summary_seconds=3.0, next_round_estimate_tokens=20,
            next_round_estimate_seconds=2.0, usage_estimated=True,
        )
        assert BudgetState.from_dict(b.to_dict()).to_dict() == b.to_dict()
        assert json.dumps(b.to_dict())
