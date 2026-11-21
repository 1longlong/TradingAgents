"""Tests for the spend gate specified in ``BUDGET_GUARD_DESIGN.md`` (§5).

These are the tests the design document claimed existed; audit C-04 found none
of the states implemented in any Python file. Each state is exercised with
mocked usage so no paid call is made.
"""

import pytest

from tradingagents import budget_guard as bg


def test_uncapped_never_blocks_and_says_so():
    gate = bg.BudgetGate(max_total_tokens=None)
    gate.record_calls([
        {"run_id": "a", "input": 1000, "output": 500, "reported": True},
        {"run_id": "b", "input": 8000, "output": 4000, "reported": True},
    ])
    assert gate.check() == bg.UNCAPPED
    info = gate.describe()
    assert info["state"] == bg.UNCAPPED
    assert info["used_tokens"] == 13500       # spend is still counted
    assert info["remaining_tokens"] is None    # ...but there is no headroom figure
    assert info["blocks_run"] is False


def test_null_cap_is_not_replaced_by_a_fallback():
    """A silent default would change what the experiment measures."""
    gate = bg.BudgetGate(max_total_tokens=None)
    assert gate.max_total_tokens is None
    assert gate.capped is False


def test_exhausted_at_the_cap_blocks_further_calls():
    gate = bg.BudgetGate(max_total_tokens=100)
    gate.record_call("a", input_tokens=60, output_tokens=40, reported=True)
    with pytest.raises(bg.BudgetExhausted):
        gate.check()
    assert gate.state == bg.EXHAUSTED
    assert gate.describe()["blocks_run"] is True


def test_ok_below_the_cap():
    gate = bg.BudgetGate(max_total_tokens=100)
    gate.record_call("a", input_tokens=10, output_tokens=5, reported=True)
    assert gate.check() == bg.OK
    assert gate.remaining == 85


def test_reserved_tokens_count_towards_the_cap():
    gate = bg.BudgetGate(max_total_tokens=100)
    gate.record_call("a", input_tokens=50, output_tokens=0, reported=True)
    gate.reserved = 50
    with pytest.raises(bg.BudgetExhausted):
        gate.check()


def test_unknown_spend_is_reported_and_is_not_zero():
    gate = bg.BudgetGate(max_total_tokens=1_000_000)
    gate.record_call("a", input_tokens=100, output_tokens=50, reported=True)
    gate.record_call("b", input_tokens=None, output_tokens=None, reported=False)
    assert gate.state == bg.UNKNOWN_SPEND
    info = gate.describe()
    assert info["used_tokens"] == 150           # the known part, not 0
    assert info["used_is_lower_bound"] is True
    assert info["unmeasured_calls"] == 1
    # The cap still looks satisfied, but the gate refuses to claim OK.
    assert info["state"] != bg.OK


def test_partial_payload_makes_spend_a_lower_bound():
    """A payload with only one half reported is not a fully known total."""
    gate = bg.BudgetGate(max_total_tokens=None)
    gate.record_call("a", input_tokens=100, output_tokens=None, reported=True)
    assert gate.state == bg.UNKNOWN_SPEND
    assert gate.used == 100
    assert gate.unmeasured_calls == 1


def test_duplicate_run_id_is_counted_once():
    gate = bg.BudgetGate(max_total_tokens=None)
    call = {"run_id": "same", "input": 10, "output": 5, "reported": True}
    gate.record_calls([call, call, call])
    assert gate.used == 15


def test_uncapped_unknown_spend_still_does_not_block():
    """UNCAPPED cannot block, but it must not hide the unknown either."""
    gate = bg.BudgetGate(max_total_tokens=None)
    gate.record_call("a", input_tokens=None, output_tokens=None, reported=False)
    assert gate.check() == bg.UNKNOWN_SPEND   # reported truthfully
    assert gate.describe()["blocks_run"] is False


@pytest.mark.parametrize("bad", [-1, 2.5, "100", True])
def test_uninterpretable_cap_raises_rather_than_defaulting(bad):
    with pytest.raises(bg.BudgetConfigError):
        bg.BudgetGate(max_total_tokens=bad)


def test_every_documented_state_is_reachable():
    reached = {
        bg.BudgetGate(max_total_tokens=None).state,
        bg.BudgetGate(max_total_tokens=10).state,
    }
    g = bg.BudgetGate(max_total_tokens=10)
    g.record_call("a", input_tokens=10, output_tokens=0, reported=True)
    reached.add(g.state)
    h = bg.BudgetGate(max_total_tokens=10)
    h.record_call("a", input_tokens=None, output_tokens=None, reported=False)
    reached.add(h.state)
    assert reached == set(bg.STATES)


# ---------------------------------------------------------------------------
# The harness must actually report the gate (audit C-04: the doc described a
# guard that no code path ever produced)
# ---------------------------------------------------------------------------
def _payload(calls, *, errors=0):
    """A minimal telemetry payload shaped like the real artifact."""
    events = []
    for i, (inp, out, reported) in enumerate(calls):
        events.append({
            "callback_run_id": f"run-{i}",
            "reported_input_tokens": inp,
            "reported_output_tokens": out,
            "usage_source": "provider" if reported else None,
        })
    total_in = sum(c[0] or 0 for c in calls)
    total_out = sum(c[1] or 0 for c in calls)
    return {
        "run": {"run_status": "completed"},
        "run_totals": {
            "llm_calls": len(calls),
            "llm_error_count": errors,
            "reported_input_tokens_sum": total_in,
            "reported_output_tokens_sum": total_out,
        },
        "usage_coverage": {
            "complete": all(c[2] and c[0] is not None and c[1] is not None
                            for c in calls),
            "calls_without_provider_usage": sum(1 for c in calls if not c[2]),
        },
        "audit_quality": {"usage_complete": True, "telemetry_complete": True},
        "llm_call_events": events,
        "agents": {},
    }


def test_extract_run_metrics_reports_uncapped():
    import scripts.token_benchmark as tb

    m = tb.extract_run_metrics(_payload([(10, 5, True), (20, 7, True)]),
                               None, 1, max_total_tokens=None)
    assert m["budget"]["state"] == bg.UNCAPPED
    assert m["budget"]["used_tokens"] == 42
    assert m["budget"]["agrees_with_telemetry"] is True
    assert m["budget"]["blocks_run"] is False


def test_extract_run_metrics_reports_unknown_spend_when_a_call_is_unmeasured():
    import scripts.token_benchmark as tb

    m = tb.extract_run_metrics(_payload([(10, 5, True), (None, None, False)]),
                               None, 1, max_total_tokens=None)
    assert m["budget"]["state"] == bg.UNKNOWN_SPEND
    assert m["budget"]["used_is_lower_bound"] is True
    assert m["budget"]["used_tokens"] == 15      # not 0, and not "unknown+15=15"
    assert m["valid"] is False                    # and the sample is not valid


def test_extract_run_metrics_honours_a_cap():
    import scripts.token_benchmark as tb

    m = tb.extract_run_metrics(_payload([(60, 40, True)]), None, 1,
                               max_total_tokens=100)
    assert m["budget"]["state"] == bg.EXHAUSTED
    assert m["budget"]["blocks_run"] is True
    assert m["budget"]["remaining_tokens"] == 0


def test_the_rounds_cap_is_read_from_the_frozen_protocol():
    """This round is uncapped *by the protocol file*, not by a default."""
    import json
    from pathlib import Path

    import scripts.token_benchmark as tb

    root = Path(tb.__file__).resolve().parent.parent
    protocol = (root / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"
                / "experiment.json")
    declared = json.loads(protocol.read_text())["budget"]["max_total_tokens"]
    assert declared is None
    assert tb._experiment_token_cap() is None
