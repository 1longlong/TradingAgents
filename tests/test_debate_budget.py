"""Phase 3B offline tests for budget accounting and reserve protection.

Covers deterministic token/time estimation, the additive run-level usage
tracker, the summary-reserve guarantee, hard-limit detection, and the
full-round eligibility check, plus the graph wiring that records a call per
Bull/Bear invocation.

Traceability: FR-DDT-003 (budget-safe termination with summary reserve),
NFR-BUD-001 (budget safety); supports INV-7 (budget safety).
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
        usage = empty_usage()
        # Legacy keys preserved exactly.
        assert usage["calls"] == 0
        assert usage["tokens"] == 0
        assert usage["seconds"] == 0.0
        assert usage["estimated"] is False
        # New provenance fields are present and honest (no fabricated values).
        assert usage["provenance"]["tokens"] is None
        assert usage["provenance"]["seconds"] is None
        assert usage["failed_calls"] == 0
        assert usage["clock"] == "unavailable"
        assert usage["transport_attempts"] is None

    def test_time_estimator_not_used_when_seconds_missing(self):
        # FR-DDT-003/NFR-BUD-001/INV-7: no measured elapsed -> time is
        # "unavailable", never character-derived, so seconds stays 0.
        u = record_call_usage(None, prompt_chars=400, response_chars=400)
        assert u["seconds"] == 0.0
        assert u["provenance"]["seconds"] == "unavailable"
        assert u["clock"] == "unavailable"

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


class TestMeasuredUsageProvenance:
    """FR-DDT-003 / NFR-BUD-001 / INV-7: measured-time accounting and honest
    provider-usage provenance (added by the DEBT-021 repair)."""

    def test_measured_elapsed_used_not_char_derived(self):
        # A long prompt with a short measured elapsed records the MEASURED time.
        u = record_call_usage(
            None, prompt_chars=100_000, response_chars=1_000, measured_seconds=0.5
        )
        assert u["seconds"] == 0.5
        assert u["provenance"]["seconds"] == "measured"
        assert u["clock"] == "measured"

    def test_no_measured_time_is_unavailable_not_estimated(self):
        u = record_call_usage(None, prompt_chars=10_000, response_chars=1_000)
        assert u["seconds"] == 0.0
        assert u["provenance"]["seconds"] == "unavailable"

    def test_validate_clock_backwards_aborts(self):
        from tradingagents.debate.budget import validate_clock_elapsed

        assert validate_clock_elapsed(10.0, 5.0)["ok"] is False
        assert validate_clock_elapsed(5.0, 5.0)["ok"] is True  # zero elapsed OK

    def test_shorter_second_call_is_not_backwards(self):
        from tradingagents.debate.budget import validate_clock_elapsed

        # A shorter second duration is valid; monotonic validation is end>=start,
        # NOT duration>=previous duration.
        assert validate_clock_elapsed(100.0, 100.2)["ok"] is True

    def test_validate_clock_nonfinite_and_bool(self):
        from tradingagents.debate.budget import validate_clock_elapsed

        assert validate_clock_elapsed(float("nan"), 1.0)["ok"] is False
        assert validate_clock_elapsed(0.0, float("inf"))["ok"] is False
        assert validate_clock_elapsed(True, 1.0)["ok"] is False
        assert validate_clock_elapsed(None, 1.0)["ok"] is False

    def test_provider_total_only_is_usable(self):
        from types import SimpleNamespace

        from tradingagents.debate.budget import extract_provider_usage

        resp = SimpleNamespace(
            usage_metadata=None,
            response_metadata={"token_usage": {"total_tokens": 999}},
        )
        pu = extract_provider_usage(resp)
        assert pu["available"] is True
        assert pu["total_tokens"] == 999
        assert pu["input_tokens"] is None and pu["output_tokens"] is None
        u = record_call_usage(None, prompt_chars=0, response_chars=0, provider_usage=pu, measured_seconds=1.0)
        assert u["tokens"] == 999
        assert u["provenance"]["tokens"] == "provider"

    def test_input_only_is_partial_not_exact_total(self):
        from types import SimpleNamespace

        from tradingagents.debate.budget import extract_provider_usage

        resp = SimpleNamespace(usage_metadata={"input_tokens": 100}, response_metadata=None)
        pu = extract_provider_usage(resp)
        assert pu["partial"] is True and pu["total_tokens"] is None
        u = record_call_usage(None, prompt_chars=400, response_chars=0, provider_usage=pu, measured_seconds=1.0)
        # Not treated as a complete exact total; labelled partial/estimated.
        assert u["provenance"]["tokens"] != "provider"
        assert u["provenance"].get("tokens_partial") is True
        assert u["input_tokens"] == 100
        # The INPUT side was provided; the OUTPUT side is missing -> partial.
        assert u.get("output_tokens_partial") is True

    def test_malformed_negative_bool_nonfinite_usage_are_missing(self):
        from types import SimpleNamespace

        from tradingagents.debate.budget import extract_provider_usage

        for md in (
            {"input_tokens": -5},
            {"input_tokens": True},
            {"total_tokens": float("nan")},
            {"total_tokens": "100"},
        ):
            pu = extract_provider_usage(SimpleNamespace(usage_metadata=md, response_metadata=None))
            assert pu["available"] is False, md

    def test_cross_source_conflict_preserved(self):
        from types import SimpleNamespace

        from tradingagents.debate.budget import extract_provider_usage

        resp = SimpleNamespace(
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            response_metadata={"token_usage": {"prompt_tokens": 120, "completion_tokens": 50, "total_tokens": 170}},
        )
        pu = extract_provider_usage(resp)
        assert pu["conflict"] is True
        assert pu["total_tokens"] == 170  # conservative (max) retained
        u = record_call_usage(None, prompt_chars=0, response_chars=0, provider_usage=pu, measured_seconds=1.0)
        assert u["provenance"]["tokens"] == "derived_conflicted"

    def test_legacy_estimated_checkpoint_stays_mixed(self):
        legacy = {"calls": 1, "tokens": 1000, "seconds": 0.0, "estimated": True}
        u = record_call_usage(legacy, prompt_chars=0, response_chars=0, measured_seconds=5.0)
        # Old estimated usage is never relabeled measured.
        assert u["estimated"] is True
        assert u["provenance"]["tokens"] == "estimated"
        assert u["provenance"]["seconds"] == "estimated"
        assert u["clock"] == "mixed"

    def test_tracker_batch_calls_charges_once(self):
        from tradingagents.debate.budget import UsageTracker

        t = UsageTracker()
        t.record_usage(calls=3, exact_tokens=100, measured_seconds=2.0)
        # logical count is N, but aggregate tokens/time charged ONCE.
        assert t.calls == 3
        assert t.tokens == 100
        assert t.seconds == 2.0


class TestSplitAndConflictPreservation:
    """NFR-BUD-001 / INV-7: cumulative split partiality and conflict-original
    preservation across calls (added by the DEBT-021 repair review)."""

    def _pu(self, resp):
        from tradingagents.debate.budget import extract_provider_usage

        return extract_provider_usage(resp)

    def test_total_only_then_full_split_stays_partial(self):
        from types import SimpleNamespace

        u = record_call_usage(
            None, prompt_chars=0, response_chars=0,
            provider_usage=self._pu(SimpleNamespace(usage_metadata=None, response_metadata={"token_usage": {"total_tokens": 110}})),
            measured_seconds=1.0,
        )
        u = record_call_usage(
            u, prompt_chars=0, response_chars=0,
            provider_usage=self._pu(SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}, response_metadata=None)),
            measured_seconds=1.0,
        )
        # The first call had no split, so the cumulative split must remain partial
        # (never presented as a complete provider split of 100/10).
        assert u.get("input_tokens_partial") is True
        assert u.get("output_tokens_partial") is True
        assert u["provenance"].get("input_tokens_partial") is True

    def test_full_then_total_only_split_stays_partial(self):
        from types import SimpleNamespace

        u = record_call_usage(
            None, prompt_chars=0, response_chars=0,
            provider_usage=self._pu(SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}, response_metadata=None)),
            measured_seconds=1.0,
        )
        u = record_call_usage(
            u, prompt_chars=0, response_chars=0,
            provider_usage=self._pu(SimpleNamespace(usage_metadata=None, response_metadata={"token_usage": {"total_tokens": 110}})),
            measured_seconds=1.0,
        )
        assert u.get("input_tokens_partial") is True
        assert u.get("output_tokens_partial") is True

    def test_full_split_only_stays_complete(self):
        from types import SimpleNamespace

        u = record_call_usage(
            None, prompt_chars=0, response_chars=0,
            provider_usage=self._pu(SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}, response_metadata=None)),
            measured_seconds=1.0,
        )
        assert not u.get("input_tokens_partial")
        assert not u.get("output_tokens_partial")
        assert u["input_tokens"] == 100 and u["output_tokens"] == 10

    def test_cross_block_conflict_originals_preserved(self):
        from types import SimpleNamespace

        resp = SimpleNamespace(
            usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            response_metadata={"token_usage": {"prompt_tokens": 101, "completion_tokens": 11, "total_tokens": 112}},
        )
        pu = self._pu(resp)
        assert pu["conflict"] is True
        originals = pu["originals"]
        # Each source is labelled.
        by_source = {o["source"]: o for o in originals}
        assert by_source["usage_metadata"]["total_tokens"] == 110
        assert by_source["response_metadata.token_usage"]["total_tokens"] == 112
        u = record_call_usage(None, prompt_chars=0, response_chars=0, provider_usage=pu, measured_seconds=1.0)
        # Persisted provenance retains both source-labelled originals, JSON-safe.
        import json

        assert u["provenance"]["tokens"] == "derived_conflicted"
        stored = u["provenance"]["tokens_conflict_originals"]
        stored_by_source = {o["source"]: o for o in stored}
        assert stored_by_source["usage_metadata"]["input_tokens"] == 100
        assert stored_by_source["response_metadata.token_usage"]["input_tokens"] == 101
        assert json.dumps(u)

    def test_multiple_conflicts_do_not_overwrite(self):
        from types import SimpleNamespace

        def conflict_resp(a, b):
            return SimpleNamespace(
                usage_metadata={"input_tokens": a, "output_tokens": 10, "total_tokens": a + 10},
                response_metadata={"token_usage": {"prompt_tokens": b, "completion_tokens": 11, "total_tokens": b + 11}},
            )

        u = record_call_usage(None, prompt_chars=0, response_chars=0, provider_usage=self._pu(conflict_resp(100, 101)), measured_seconds=1.0)
        u = record_call_usage(u, prompt_chars=0, response_chars=0, provider_usage=self._pu(conflict_resp(200, 201)), measured_seconds=1.0)
        stored = u["provenance"]["tokens_conflict_originals"]
        call_indices = {o["call_index"] for o in stored}
        # Both calls' conflicts are preserved (4 originals across 2 calls).
        assert call_indices == {0, 1}
        assert len(stored) == 4
        assert any(o["call_index"] == 0 and o["input_tokens"] == 100 for o in stored)
        assert any(o["call_index"] == 1 and o["input_tokens"] == 200 for o in stored)
