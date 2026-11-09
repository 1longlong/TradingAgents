"""Unit tests for the analyst tool-governance module.

Everything here is offline and pure: no model, no network, no vendor. The
governance module never calls a tool itself; where a real ``ToolNode`` is used
it runs local fake tools only, to prove the planned calls are accepted as-is.
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode

from tradingagents.agents.utils import tool_governance as tg
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorAuthenticationError

RUN = "run-1"
ANALYST = "market"
TRADE_DATE = "2026-08-14"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call(call_id, name, args=None, **kwargs):
    return {"id": call_id, "name": name, "args": dict(args or {}, **kwargs)}


def _context(**overrides):
    values = {
        "analyst": ANALYST,
        "run_id": RUN,
        "instrument": "AAPL",
        "trade_date": TRADE_DATE,
        "vendor_chains": {
            "get_stock_data": "yfinance",
            "get_indicators": "yfinance",
            "get_news": "yfinance",
            "get_balance_sheet": "yfinance",
        },
    }
    values.update(overrides)
    return tg.ToolContext(**values)


def _fp(call, **overrides):
    return _context(**overrides).fingerprint(call)


def _scope(**overrides):
    scope = tg.get_scope(tg.new_state(RUN), ANALYST, RUN)
    scope.update(overrides)
    return scope


def _plan(scope, calls, limits=None, **kwargs):
    return tg.plan_tool_round(
        scope, calls, limits, context=kwargs.pop("context", None) or _context(), **kwargs
    )


def _run_round(scope, calls, limits=None, results=None, **default_result):
    """Plan, start and record one new round -- the whole loop, no tool."""
    plan = _plan(scope, calls, limits)
    scope = tg.record_round_start(scope, plan, limits)
    results = results or {}
    for entry in plan.execute:
        scope = _record(scope, entry, results.get(entry["id"], default_result))
    return scope, plan


def _record(scope, entry, outcome, text=None):
    return tg.record_tool_result(
        scope,
        tool_call_id=entry["id"],
        tool_name=entry["name"],
        fingerprint=entry["fingerprint"],
        result=outcome.get("result", text or "rows..."),
        raised=outcome.get("raised", False),
        cacheable_success=outcome.get("cacheable_success"),
        reason=outcome.get("reason"),
    )


STOCK = _call("c1", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
              end_date="2026-08-14")
Rsi = _call("r1", "get_indicators", symbol="AAPL", indicator="rsi", curr_date=TRADE_DATE)


# ---------------------------------------------------------------------------
# Fingerprint scope: instrument, date, vendor config, run scope
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_instrument_change_is_not_reused():
    assert _fp(STOCK) == _fp(_call("c2", "get_stock_data", symbol="aapl",
                                   start_date="2026-08-01", end_date="2026-08-14"))
    assert _fp(STOCK) != _fp(_call("c2", "get_stock_data", symbol="MSFT",
                                   start_date="2026-08-01", end_date="2026-08-14"))
    assert _fp(STOCK) != _fp(STOCK, instrument="MSFT")


@pytest.mark.unit
def test_run_instrument_reaches_the_fingerprint():
    bare = _call("c1", "get_balance_sheet", ticker="AAPL")
    assert _fp(bare, instrument="AAPL") != _fp(bare, instrument="MSFT")


@pytest.mark.unit
def test_date_change_is_not_reused():
    later = _call("c1", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
                  end_date="2026-08-12")
    assert _fp(STOCK) != _fp(later)
    # A model date beyond the run date is clamped by the tool itself, so it is
    # the same request -- the existing as_of_window rule, not invention.
    clamped = _call("c1", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
                    end_date="2026-12-31")
    assert _fp(STOCK) == _fp(clamped)
    # A different run date is a different request even with the same arguments.
    assert _fp(STOCK) != _fp(STOCK, trade_date="2026-08-13")


@pytest.mark.unit
def test_data_source_config_change_is_not_reused():
    assert _fp(STOCK) != _fp(STOCK, vendor_chains={"get_stock_data": "alpha_vantage"})


@pytest.mark.unit
def test_live_router_config_is_read_when_no_chain_is_given():
    set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
    first = tg.request_fingerprint(STOCK, analyst=ANALYST, run_id=RUN, trade_date=TRADE_DATE)
    set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})
    second = tg.request_fingerprint(STOCK, analyst=ANALYST, run_id=RUN, trade_date=TRADE_DATE)
    assert first != second


@pytest.mark.unit
def test_run_and_analyst_scope_change_is_not_reused():
    assert _fp(STOCK) != _fp(STOCK, run_id="run-2")
    assert _fp(STOCK) != _fp(STOCK, analyst="news")


# ---------------------------------------------------------------------------
# Fingerprint normalisation: only what the field explicitly allows
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schema_defaults_are_equivalent_to_omitting_them():
    omitted = _call("a", "get_indicators", symbol="AAPL", indicator="rsi",
                    curr_date=TRADE_DATE)
    explicit = _call("b", "get_indicators", symbol="AAPL", indicator="rsi",
                     curr_date=TRADE_DATE, look_back_days=30)
    other = _call("c", "get_indicators", symbol="AAPL", indicator="rsi",
                  curr_date=TRADE_DATE, look_back_days=60)
    assert _fp(omitted) == _fp(explicit)
    assert _fp(omitted) != _fp(other)


@pytest.mark.unit
def test_argument_order_is_stable():
    first = _call("a", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
                  end_date="2026-08-14")
    second = {"id": "b", "name": "get_stock_data",
              "args": {"end_date": "2026-08-14", "start_date": "2026-08-01",
                       "symbol": "AAPL"}}
    assert _fp(first) == _fp(second)


@pytest.mark.unit
def test_free_text_is_not_lowercased_or_stripped():
    upper = _call("a", "get_prediction_markets", topic="Fed rate cut")
    lower = _call("b", "get_prediction_markets", topic="fed rate cut")
    padded = _call("c", "get_prediction_markets", topic="Fed rate cut ")
    assert _fp(upper) != _fp(lower)
    assert _fp(upper) != _fp(padded)


@pytest.mark.unit
def test_list_arguments_are_not_sorted():
    # A schema whose argument is a real list: order must survive.
    schema = {"type": "object", "properties": {"topic": {"type": "array"}}, "required": ["topic"]}
    ctx = _context(schemas={"get_prediction_markets": schema})
    a = ctx.fingerprint(_call("a", "get_prediction_markets", topic=["rsi", "macd"]))
    b = ctx.fingerprint(_call("b", "get_prediction_markets", topic=["macd", "rsi"]))
    assert a != b


@pytest.mark.unit
def test_comma_parameters_are_not_sorted():
    a = _call("a", "get_indicators", symbol="AAPL", indicator="rsi,macd", curr_date=TRADE_DATE)
    b = _call("b", "get_indicators", symbol="AAPL", indicator="macd,rsi", curr_date=TRADE_DATE)
    assert _fp(a) != _fp(b)


@pytest.mark.unit
def test_partial_indicator_set_is_not_the_full_set():
    part = _call("a", "get_indicators", symbol="AAPL", indicator="rsi", curr_date=TRADE_DATE)
    full = _call("b", "get_indicators", symbol="AAPL", indicator="rsi,macd,atr",
                 curr_date=TRADE_DATE)
    assert _fp(part) != _fp(full)


@pytest.mark.unit
def test_unknown_tool_has_no_fingerprint():
    unknown = _call("a", "mystery_tool", x=1)
    assert tg.tool_schema("mystery_tool") is None
    with pytest.raises(tg.MalformedCallError) as excinfo:
        _fp(unknown)
    assert excinfo.value.reason == tg.INVALID_CALL_UNKNOWN_TOOL
    assert not tg.is_reusable_read_only_tool("mystery_tool")


# ---------------------------------------------------------------------------
# Fingerprint validation: the fingerprint never stands in for the tool's own
# ----------------------------------------------------------------arg checks--
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_omitted_required_argument_is_not_repaired_by_the_run_date():
    # A bare str schema: the run date must NOT be invented for it.
    schema = {"type": "object", "properties": {"symbol": {"type": "string"}},
              "required": ["symbol", "start_date"]}
    ctx = _context(schemas={"get_stock_data": schema})
    with pytest.raises(tg.MalformedCallError) as excinfo:
        ctx.fingerprint(_call("a", "get_stock_data", symbol="AAPL"))
    assert "missing_required:start_date" in excinfo.value.reason


@pytest.mark.unit
def test_omitted_required_trade_date_is_equivalent_to_the_injected_run_date():
    # ``trade_date`` is InjectedState: the framework supplies it, so both the
    # omitted and the injected form are the same request.
    schema = {"type": "object",
              "properties": {"x": {"type": "integer"}, "trade_date": {"type": "string"}},
              "required": ["trade_date"]}
    ctx = _context(schemas={"get_indicator": schema})
    assert ctx.fingerprint(_call("a", "get_indicator", x=1)) == ctx.fingerprint(
        _call("b", "get_indicator", x=1, trade_date=TRADE_DATE)
    )


@pytest.mark.unit
def test_slash_date_is_kept_verbatim_like_the_tool_keeps_it():
    # The real tool parses only ``YYYY-MM-DD``; a slash date is not that day,
    # it is passed through verbatim, so the two are different requests. The
    # fingerprint does not swap one style for another.
    slash = _call("a", "get_stock_data", symbol="AAPL", start_date="2026/08/01",
                  end_date="2026/08/14")
    dashes = _call("b", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
                   end_date="2026-08-14")
    assert _fp(slash) != _fp(dashes)


@pytest.mark.unit
def test_date_truncation_matches_the_tool():
    # The tool clamps the end to the run date; the fingerprint must agree.
    beyond = _call("a", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
                   end_date="2026-09-30")
    assert _fp(beyond) == _fp(STOCK)
    # ... but only for the tools that do it: get_insider_transactions has no
    # date argument, so the run date is never folded into its arguments.
    assert tg._tool_date_rewrite("get_insider_transactions", {"ticker": "AAPL"},
                                 TRADE_DATE) == {"ticker": "AAPL"}
    args_payload = tg._fingerprint_payload(
        _call("b", "get_insider_transactions", ticker="AAPL"),
        tg.tool_schema("get_insider_transactions"),
        analyst=ANALYST, run_id=RUN, instrument="AAPL",
        trade_date=TRADE_DATE, vendor_chain="yfinance",
    )["args"]
    assert args_payload == {"ticker": "AAPL"}


@pytest.mark.unit
def test_optional_none_date_is_left_for_the_tool_to_default():
    # ``get_balance_sheet(curr_date=None)`` is *rejected* by the tool's own
    # pydantic model, so the fingerprint rejects it too -- it must not be
    # repaired into a valid request.
    explicit_none = _call("a", "get_balance_sheet", ticker="AAPL", curr_date=None)
    with pytest.raises(tg.MalformedCallError) as excinfo:
        _fp(explicit_none)
    assert excinfo.value.reason.endswith("type_mismatch:curr_date")

    # Omitting it is valid: the schema default is None and the tool's ``as_of``
    # turns that into the run date, so it equals the explicit run date.
    omitted = _call("b", "get_balance_sheet", ticker="AAPL")
    injected = _call("c", "get_balance_sheet", ticker="AAPL", curr_date=TRADE_DATE)
    assert _fp(omitted) == _fp(injected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "call, reason",
    [
        (_call("a", "get_stock_data", symbol="AAPL", start_date="2026-08-01"),
         "missing_required:end_date"),
        (_call("a", "get_stock_data", symbol="AAPL", start_date="2026-08-01",
               end_date=20260101), "type_mismatch:end_date"),
        (_call("a", "get_indicators", symbol="AAPL", indicator="rsi",
               curr_date=TRADE_DATE, look_back_days=True), "type_mismatch:look_back_days"),
        (_call("a", "get_indicators", symbol="AAPL", indicator="rsi",
               curr_date=None), "type_mismatch:curr_date"),
        (_call("a", "get_indicators", symbol="AAPL", indicator="rsi",
               curr_date=TRADE_DATE, nope=1), "unexpected_argument:nope"),
    ],
)
def test_invalid_arguments_are_rejected_before_any_lookup(call, reason):
    assert tg._validate_args(tg.tool_schema(call["name"]), call["args"], TRADE_DATE) == reason
    with pytest.raises(tg.MalformedCallError) as excinfo:
        _fp(call)
    assert excinfo.value.reason == f"{tg.INVALID_CALL_SCHEMA}:{reason}"


@pytest.mark.unit
def test_invalid_arguments_never_hit_the_cache():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope, _ = _run_round(_scope(), [STOCK], limits, results={"c1": {"cacheable_success": True}})
    assert scope["cache"]
    # Same intent, but the tool would reject it: a missing end_date.
    broken = _call("c2", "get_stock_data", symbol="AAPL", start_date="2026-08-01")
    plan = _plan(scope, [broken], limits)
    assert plan.must_abort
    assert plan.invalid[0]["reason"].startswith(tg.INVALID_CALL_SCHEMA)
    assert plan.execute == () and plan.reuse == () and plan.messages == ()


@pytest.mark.unit
def test_schema_validation_agrees_with_the_real_tool():
    # The module's validator and the tool's own pydantic model agree on what
    # is rejected -- offline: a validation failure never reaches the body.
    from tradingagents.agents.utils.agent_utils import get_indicators

    bad = {"symbol": "AAPL", "indicator": "rsi"}  # curr_date missing
    assert tg._validate_args(tg.tool_schema("get_indicators"), bad) == "missing_required:curr_date"
    with pytest.raises(Exception) as excinfo:
        get_indicators.invoke(bad)
    assert "curr_date" in str(excinfo.value)

    wrong_type = {"symbol": "AAPL", "indicator": "rsi", "curr_date": TRADE_DATE,
                  "look_back_days": "thirty"}
    assert tg._validate_args(tg.tool_schema("get_indicators"), wrong_type) == (
        "type_mismatch:look_back_days"
    )
    with pytest.raises(Exception) as excinfo:
        get_indicators.invoke(wrong_type)
    assert "look_back_days" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Planning: execute / reuse / block
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fresh_batch_executes_every_call_and_keeps_its_id():
    plan = _plan(_scope(), [STOCK, Rsi], tg.ToolLimits(max_rounds=3, max_calls=8))
    assert plan.executed_call_ids == ("c1", "r1")
    assert plan.reuse == () and plan.block == ()
    assert (plan.rounds, plan.requested, plan.executed, plan.reused, plan.blocked) == (
        1, 2, 2, 0, 0)
    assert plan.mode == "new" and not plan.close_after_execute


@pytest.mark.unit
def test_executed_calls_are_complete_tool_calls():
    plan = _plan(_scope(), [STOCK], tg.ToolLimits(max_rounds=3, max_calls=3))
    (call,) = plan.executed_calls
    assert call["id"] == "c1"
    assert call["name"] == "get_stock_data"
    assert call["args"] == {"symbol": "AAPL", "start_date": "2026-08-01",
                            "end_date": "2026-08-14"}
    # A real ToolNode only treats a dict as a tool call when ``type`` says so.
    assert call["type"] == "tool_call"
    assert json.loads(json.dumps(plan.executed_calls)) == [call]


@pytest.mark.unit
def test_planning_is_pure():
    scope = _scope()
    before = json.dumps(scope, sort_keys=True)
    _plan(scope, [STOCK], tg.ToolLimits(max_rounds=2))
    assert json.dumps(scope, sort_keys=True) == before


@pytest.mark.unit
def test_reuse_pairs_the_current_request_id_not_the_old_message_id():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope, _ = _run_round(_scope(), [STOCK], limits, results={"c1": {"cacheable_success": True}})
    plan = _plan(scope, [dict(STOCK, id="c9")], limits)

    assert plan.executed_calls == ()
    (reused,) = plan.reuse
    assert reused["id"] == "c9"
    assert reused["source_tool_call_id"] == "c1"
    assert reused["tool_message"]["tool_call_id"] == "c9"
    assert reused["tool_message"]["tool_call_id"] != reused["source_tool_call_id"]
    assert "rows..." in reused["tool_message"]["content"]


@pytest.mark.unit
def test_reuse_only_round_still_spends_a_round():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope, _ = _run_round(_scope(), [STOCK], limits, results={"c1": {"cacheable_success": True}})
    scope, plan = _run_round(scope, [dict(STOCK, id="c2")], limits)

    assert plan.executed == 0 and plan.reused == 1
    assert scope["rounds"] == 2
    assert scope["reused"] == 1
    assert scope["executed"] == 1          # the reuse spends no execution slot
    assert scope["requested"] == 2


@pytest.mark.unit
def test_all_blocked_round_still_spends_a_round():
    limits = tg.ToolLimits(max_rounds=5, max_calls=3)
    scope, _ = _run_round(_scope(), [STOCK], limits, results={"c1": {"cacheable_success": True}})
    bad = _call("c5", "get_stock_data", symbol="ZZZZ", start_date="2026-08-01",
                end_date="2026-08-14")
    scope, _ = _run_round(scope, [bad], limits,
                          results={"c5": {"result": "NO_DATA_AVAILABLE: nope"}})
    assert scope["executed"] == 2
    scope, plan = _run_round(scope, [dict(bad, id="c6")], limits)

    assert plan.executed == 0 and plan.reused == 0 and plan.blocked == 1
    assert plan.block[0]["reason"] == tg.BLOCK_DUPLICATE_FAILED
    assert scope["rounds"] == 3
    assert scope["blocked"] == 1


@pytest.mark.unit
def test_round_limit_closes_the_analyst():
    limits = tg.ToolLimits(max_rounds=1, max_calls=10)
    scope, plan = _run_round(_scope(), [STOCK, Rsi], limits)
    assert plan.close_after_execute is True
    assert scope["closed"] is True

    after = _plan(scope, [dict(STOCK, id="c")], limits)
    assert after.executed_calls == () and after.reuse == ()
    assert {e["reason"] for e in after.block} == {tg.BLOCK_ROUND_LIMIT}
    assert tg.round_limit_reached(scope, limits) is True


@pytest.mark.unit
def test_call_limit_is_decided_for_the_whole_batch_up_front():
    limits = tg.ToolLimits(max_rounds=10, max_calls=2)
    calls = [_call(name, "get_indicators", symbol="AAPL", indicator=name, curr_date=TRADE_DATE)
             for name in ("rsi", "macd", "atr")]
    plan = _plan(_scope(), calls, limits)

    assert plan.executed_call_ids == ("rsi", "macd")
    assert [e["id"] for e in plan.block] == ["atr"]
    assert plan.block[0]["reason"] == tg.BLOCK_CALL_LIMIT
    assert plan.close_after_execute is True
    assert plan.block[0]["tool_message"]["tool_call_id"] == "atr"


@pytest.mark.unit
def test_call_limit_counts_against_what_was_already_executed():
    limits = tg.ToolLimits(max_rounds=10, max_calls=3)
    scope, _ = _run_round(_scope(), [
        _call("a", "get_indicators", symbol="AAPL", indicator="rsi", curr_date=TRADE_DATE),
        _call("b", "get_indicators", symbol="AAPL", indicator="macd", curr_date=TRADE_DATE),
    ], limits)
    plan = _plan(scope, [
        _call("c", "get_indicators", symbol="AAPL", indicator="atr", curr_date=TRADE_DATE),
        _call("d", "get_indicators", symbol="AAPL", indicator="boll", curr_date=TRADE_DATE),
    ], limits)

    assert plan.executed_call_ids == ("c",)
    assert [e["id"] for e in plan.block] == ["d"]


@pytest.mark.unit
def test_duplicate_within_one_batch_executes_once():
    plan = _plan(_scope(), [dict(STOCK, id="a"), dict(STOCK, id="b")],
                 tg.ToolLimits(max_rounds=3, max_calls=5))
    assert plan.executed_call_ids == ("a",)
    assert plan.block[0]["reason"] == tg.BLOCK_DUPLICATE_IN_BATCH
    assert plan.reuse == ()   # nothing is served from a result not produced yet


@pytest.mark.unit
def test_duplicate_after_success_is_reused_not_executed():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope, _ = _run_round(_scope(), [dict(STOCK, id="a")], limits,
                          results={"a": {"cacheable_success": True}})
    plan = _plan(scope, [dict(STOCK, id="b"), dict(STOCK, id="c")], limits)
    assert plan.executed_calls == ()
    assert [e["id"] for e in plan.reuse] == ["b", "c"]


@pytest.mark.unit
def test_closed_scope_blocks_before_reuse():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope, _ = _run_round(_scope(), [STOCK], limits, results={"c1": {"cacheable_success": True}})
    scope = {**scope, "closed": True}
    plan = _plan(scope, [dict(STOCK, id="z")], limits)
    assert plan.reuse == ()
    assert plan.block[0]["reason"] == tg.BLOCK_ROUND_LIMIT


# ---------------------------------------------------------------------------
# Batch structure and call ids: fail clearly, never pair a fabricated id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_batch_structure_is_checked_before_anything_else():
    plan = _plan(_scope(), None, tg.ToolLimits(max_rounds=2))
    assert plan.must_abort and plan.invalid_reason == tg.INVALID_BATCH_NONE
    assert plan.execute == () and plan.messages == ()

    empty = _plan(_scope(), [], tg.ToolLimits(max_rounds=2))
    assert empty.invalid_reason == tg.INVALID_BATCH_EMPTY


@pytest.mark.unit
@pytest.mark.parametrize("element", [None, "call", 3])
def test_non_mapping_element_aborts_without_a_message(element):
    plan = _plan(_scope(), [STOCK, element], tg.ToolLimits(max_rounds=2, max_calls=2))
    assert plan.must_abort
    assert plan.invalid[0]["reason"] == tg.INVALID_BATCH_CALL
    assert plan.execute == () and plan.block == ()

    # Recording an aborted batch changes nothing at all.
    scope = _scope()
    assert tg.record_round_start(scope, plan, tg.ToolLimits(max_rounds=2)) == scope


@pytest.mark.unit
def test_missing_or_duplicate_ids_abort_the_batch():
    no_id = {"name": "get_stock_data", "args": dict(STOCK["args"])}
    plan = _plan(_scope(), [STOCK, no_id], tg.ToolLimits(max_rounds=2, max_calls=2))
    assert plan.must_abort and plan.invalid[0]["reason"] == tg.INVALID_BATCH_MISSING_ID

    duplicate = _plan(_scope(), [dict(STOCK, id="x"), dict(STOCK, id="x")],
                      tg.ToolLimits(max_rounds=2, max_calls=2))
    assert duplicate.must_abort
    assert duplicate.invalid[0] == {
        "reason": tg.INVALID_BATCH_DUPLICATE_ID, "index": 1, "id": "x"
    }
    assert duplicate.execute == () and duplicate.messages == ()


@pytest.mark.unit
def test_no_plan_message_ever_carries_a_none_id():
    plan = _plan(
        _scope(),
        [{"name": "get_stock_data", "args": {}},          # no id at all
         {"id": "x", "args": {}},                          # no name
         {"id": "y", "name": "get_stock_data", "args": "oops"}],  # args not a mapping
        tg.ToolLimits(max_rounds=2, max_calls=2),
    )
    assert plan.must_abort
    assert all(item["id"] != "None" for item in plan.invalid)
    assert plan.messages == () and plan.block == ()


@pytest.mark.unit
def test_a_malformed_call_in_a_batch_prevents_the_whole_execution():
    broken = _call("bad", "get_stock_data", symbol="AAPL", start_date="2026-08-01")
    plan = _plan(_scope(), [STOCK, broken], tg.ToolLimits(max_rounds=2, max_calls=2))
    assert plan.must_abort
    assert plan.invalid[0]["id"] == "bad"
    assert plan.executed_calls == ()


# ---------------------------------------------------------------------------
# Registration: a new round vs. a dispatched or replayed one
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replanning_after_registration_resumes_instead_of_being_removed():
    limits = tg.ToolLimits(max_rounds=1, max_calls=1)
    scope = _scope()
    first = _plan(scope, [STOCK], limits)
    assert first.mode == "new" and first.executed_call_ids == ("c1",)
    scope = tg.record_round_start(scope, first, limits)
    assert scope["closed"] is True      # the last round and call were spent

    # Same batch again: it reads the saved plan back, it is not re-decided.
    again = _plan(scope, [STOCK], limits)
    assert again.mode == "resume"
    assert again.rounds == 0 and again.resumed
    assert again.executed_call_ids == ("c1",)
    assert again.block == ()
    assert tg.record_round_start(scope, again, limits) is scope
    assert scope["rounds"] == 1


@pytest.mark.unit
def test_dispatch_twice_executes_twice_but_spends_nothing_more():
    limits = tg.ToolLimits(max_rounds=1, max_calls=1)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    again = _plan(scope, [STOCK], limits, dispatched=True)
    scope = tg.record_round_start(scope, again, limits)
    assert again.mode == "resume"
    assert again.executed_call_ids == ("c1",)
    assert scope["executed"] == 1 and scope["rounds"] == 1


@pytest.mark.unit
def test_resume_after_registration_before_any_result():
    limits = tg.ToolLimits(max_rounds=1, max_calls=2)
    scope = _scope()
    plan = _plan(scope, [STOCK, Rsi], limits)
    scope = tg.record_round_start(scope, plan, limits)

    resumed = _plan(scope, [STOCK, Rsi], limits, dispatched=True)
    assert resumed.mode == "resume"
    assert resumed.executed_call_ids == ("c1", "r1")
    assert resumed.reuse == () and resumed.block == ()
    # Fingerprints did not drift with the changed allowance.
    assert [e["fingerprint"] for e in resumed.execute] == [
        e["fingerprint"] for e in plan.execute
    ]


@pytest.mark.unit
def test_resume_with_partial_results_only_returns_the_remainder():
    limits = tg.ToolLimits(max_rounds=1, max_calls=2)
    scope = _scope()
    plan = _plan(scope, [STOCK, Rsi], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = _record(scope, plan.execute[0], {"cacheable_success": True})

    resumed = _plan(scope, [STOCK, Rsi], limits, dispatched=True)
    assert resumed.mode == "resume"
    assert resumed.executed_call_ids == ("r1",)      # the finished call does not run again
    (done,) = resumed.reuse
    # A finished call is replayed from its own record, not "reused" from cache.
    assert done["action"] == "replay"
    assert done["id"] == "c1"
    assert done["tool_message"]["tool_call_id"] == "c1"
    assert done["status"] == tg.CACHEABLE_SUCCESS
    assert done["tool_message"]["content"] == "rows..."


@pytest.mark.unit
def test_a_fully_finished_batch_replays_its_messages_and_executes_nothing():
    limits = tg.ToolLimits(max_rounds=1, max_calls=1)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = _record(scope, plan.execute[0], {"cacheable_success": True})

    replay = _plan(scope, [STOCK], limits)
    assert replay.mode == "replay"
    assert replay.executed_calls == () and replay.executed == 0
    (message,) = replay.messages
    assert message["tool_call_id"] == "c1"
    assert message["content"].startswith("rows...")


@pytest.mark.unit
def test_a_non_reusable_result_replays_instead_of_executing_again():
    limits = tg.ToolLimits(max_rounds=1, max_calls=1)
    news = _call("n1", "get_news", ticker="AAPL", start_date="2026-08-07",
                 end_date="2026-08-14")
    scope = _scope()
    plan = _plan(scope, [news], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = _record(scope, plan.execute[0], {"cacheable_success": True})

    replay = _plan(scope, [news], limits)
    assert replay.mode == "replay"
    assert replay.executed_calls == ()
    assert scope["outcomes"][tg.NON_REUSABLE_SUCCESS] == 1


@pytest.mark.unit
def test_same_id_with_changed_arguments_is_not_a_resume():
    limits = tg.ToolLimits(max_rounds=2, max_calls=2)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)

    changed = _call("c1", "get_stock_data", symbol="MSFT", start_date="2026-08-01",
                    end_date="2026-08-14")
    resumed = _plan(scope, [changed], limits, dispatched=True)
    assert resumed.must_abort
    assert resumed.invalid[0]["reason"] == tg.INVALID_BATCH_CHANGED
    assert resumed.executed_calls == ()


@pytest.mark.unit
def test_dispatched_batch_without_a_saved_plan_is_rejected():
    plan = _plan(_scope(), [STOCK], tg.ToolLimits(max_rounds=2), dispatched=True)
    assert plan.must_abort and plan.invalid_reason == tg.INVALID_BATCH_REPLAY_ONLY


# ---------------------------------------------------------------------------
# Classification and recording: only a confirmed success is ever reused
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"result": "rows", "cacheable_success": True}, tg.CACHEABLE_SUCCESS),
        ({"result": "rows"}, tg.UNKNOWN),
        ({"result": "NO_DATA_AVAILABLE: nothing"}, tg.MISSING_DATA),
        ({"result": "DATA_UNAVAILABLE: vendor chain exhausted"}, tg.DEGRADED),
        ({"result": "rows", "raised": True}, tg.ERROR),
        ({"result": None}, tg.UNKNOWN),
    ],
)
def test_classification_never_infers_success_from_absence(kwargs, expected):
    assert tg.classify_tool_result(**kwargs) == expected


@pytest.mark.unit
def test_only_a_confirmed_reusable_success_is_cached():
    limits = tg.ToolLimits(max_rounds=10, max_calls=10)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = _record(scope, plan.execute[0], {"result": "rows"})   # no confirmation
    assert scope["cache"] == {}
    assert plan.execute[0]["fingerprint"] in scope["attempts"]

    # A confirmed success for the same request (from a later call) clears the
    # earlier failure record and becomes reusable.
    done = tg.record_tool_result(
        scope, tool_call_id="c2", tool_name="get_stock_data",
        fingerprint=plan.execute[0]["fingerprint"], result="rows",
        cacheable_success=True,
    )
    assert plan.execute[0]["fingerprint"] in done["cache"]
    assert plan.execute[0]["fingerprint"] not in done["attempts"]
    # Re-recording the *same* call id is idempotent: it does not overwrite.
    assert _record(done, plan.execute[0], {"cacheable_success": True})["results"]["c1"][
        "status"
    ] == tg.UNKNOWN


@pytest.mark.unit
def test_a_non_reusable_tool_result_is_never_cached():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    news = _call("n1", "get_news", ticker="AAPL", start_date="2026-08-07",
                 end_date="2026-08-14")
    scope = _scope()
    plan = _plan(scope, [news], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = _record(scope, plan.execute[0], {"cacheable_success": True})

    assert scope["cache"] == {}
    assert scope["results"]["n1"]["status"] == tg.NON_REUSABLE_SUCCESS
    # The same request again is executed, not served from a record.
    again = _plan(scope, [dict(news, id="n2")], limits)
    assert again.executed_call_ids == ("n2",)


@pytest.mark.unit
def test_a_tool_message_with_error_status_is_not_a_success():
    msg = ToolMessage(content="rows", tool_call_id="x", status="error")
    scope = tg.record_tool_result(_scope(), tool_call_id="x", tool_name="get_stock_data",
                                  fingerprint="fp", result=msg, cacheable_success=True)
    assert scope["cache"] == {}
    assert scope["results"]["x"]["status"] == tg.ERROR


@pytest.mark.unit
def test_recording_without_a_call_id_is_refused():
    with pytest.raises(ValueError):
        tg.record_tool_result(_scope(), tool_call_id=None, result="rows")


@pytest.mark.unit
def test_recording_the_same_call_twice_changes_nothing():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    once = _record(scope, plan.execute[0], {"cacheable_success": True})
    twice = _record(once, plan.execute[0], {"cacheable_success": True})
    assert twice["outcomes"] == once["outcomes"]
    assert twice["cache"] == once["cache"]


@pytest.mark.unit
def test_recording_the_same_round_twice_spends_it_once():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    once = tg.record_round_start(scope, plan, limits)
    assert tg.record_round_start(once, plan, limits) is once
    assert once["rounds"] == 1 and once["executed"] == 1


@pytest.mark.unit
def test_a_repeat_failure_is_blocked_not_retried():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = _record(scope, plan.execute[0], {"result": "DATA_UNAVAILABLE: down"})
    assert scope["outcomes"][tg.DEGRADED] == 1

    again = _plan(scope, [dict(STOCK, id="c2")], limits)
    assert again.executed_calls == ()
    assert again.block[0]["reason"] == tg.BLOCK_DUPLICATE_FAILED


@pytest.mark.unit
def test_analyst_and_run_records_are_isolated():
    state = tg.new_state(RUN)
    tg.with_scope(state, ANALYST, {"rounds": 3, "run_id": RUN}, RUN)
    other_analyst = tg.get_scope(state, "news", RUN)
    assert other_analyst.get("rounds", 0) == 0
    # A stale record from another run is not reused.
    assert tg.get_scope(state, ANALYST, "run-2").get("rounds", 0) == 0


@pytest.mark.unit
def test_scope_is_json_serialisable():
    limits = tg.ToolLimits(max_rounds=3, max_calls=3)
    scope, plan = _run_round(_scope(), [STOCK], limits,
                             results={"c1": {"cacheable_success": True}})
    assert json.loads(json.dumps(scope)) == json.loads(json.dumps(scope))
    assert json.loads(json.dumps(plan.executed_calls)) == json.loads(
        json.dumps(plan.executed_calls)
    )


@pytest.mark.unit
def test_requested_equals_executed_plus_reused_plus_blocked():
    limits = tg.ToolLimits(max_rounds=10, max_calls=10)
    scope, _ = _run_round(
        _scope(),
        [STOCK, _call("f1", "get_news", ticker="AAPL", start_date="2026-08-07",
                      end_date="2026-08-14")],
        limits,
        results={
            "c1": {"cacheable_success": True},
            "f1": {"result": "DATA_UNAVAILABLE: chain exhausted"},
        },
    )
    # One reuse (c1's success) and one execute in the second round.
    scope, plan = _run_round(
        scope,
        [dict(STOCK, id="c2"), Rsi],
        limits,
        results={"r1": {"cacheable_success": True}},
    )
    assert plan.requested == plan.executed + plan.reused + plan.blocked
    assert (plan.executed, plan.reused, plan.blocked) == (1, 1, 0)

    # A batch mixing all three in a single round.
    fine = _call("x2", "get_indicators", symbol="AAPL", indicator="macd",
                 curr_date=TRADE_DATE)
    mixed = _plan(
        scope,
        [
            dict(STOCK, id="c3"),      # reuse: cached success
            dict(Rsi, id="r3"),        # reuse: cached success
            dict(STOCK, id="c4"),      # would be reuse too
            fine,                      # execute: first time seen
            _call("x3", "get_indicators", symbol="AAPL", indicator="macd",
                  curr_date=TRADE_DATE),   # duplicate_in_batch of ``fine``
        ],
        limits,
    )
    assert mixed.requested == 5
    assert (mixed.executed, mixed.reused, mixed.blocked) == (1, 3, 1)
    assert mixed.requested == mixed.executed + mixed.reused + mixed.blocked
    charged = tg.record_round_start(scope, mixed, limits)
    delta = {
        key: charged[key] - scope[key]
        for key in ("requested", "executed", "reused", "blocked")
    }
    assert delta == {"requested": 5, "executed": 1, "reused": 3, "blocked": 1}
    assert charged["requested"] == (
        charged["executed"] + charged["reused"] + charged["blocked"])


@pytest.mark.unit
def test_malformed_calls_are_blocked_but_not_requested():
    scope = tg.record_malformed(_scope(), 2)
    assert scope["malformed"] == 2
    assert scope["blocked"] == 2
    assert scope["requested"] == 0
    # An aborted batch charges nothing at all.
    plan = _plan(_scope(), [{"name": "get_stock_data", "args": {}}],
                 tg.ToolLimits(max_rounds=2))
    assert plan.must_abort
    assert (plan.requested, plan.executed, plan.reused, plan.blocked) == (0, 0, 0, 0)


@pytest.mark.unit
def test_whole_record_accounting_identity():
    limits = tg.ToolLimits(max_rounds=10, max_calls=10)
    scope, _ = _run_round(_scope(), [STOCK], limits,
                          results={"c1": {"cacheable_success": True}})
    scope, _ = _run_round(scope, [dict(STOCK, id="c2"), Rsi], limits,
                          results={"r1": {"cacheable_success": True}})
    scope = tg.record_malformed(scope, 3)
    assert scope["requested"] + scope["malformed"] == (
        scope["executed"] + scope["reused"] + scope["blocked"])


# ---------------------------------------------------------------------------
# Compatibility with a real ToolNode (local fake tools, no network)
# ---------------------------------------------------------------------------


@tool
def _fake_quote(symbol: str, start_date: str, end_date: str) -> str:
    """Return a canned quote for one symbol."""
    return f"quote {symbol} {start_date}..{end_date}"


@tool
def _fake_rsi(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    """Return a canned indicator value."""
    return f"{indicator} for {symbol} on {curr_date}"


class _FakeState(TypedDict, total=False):
    calls: Any
    out: Any


def _run_in_a_real_graph(node: ToolNode, calls: list) -> list:
    """Run a real ``ToolNode`` the way a graph does, on local fake tools.

    ``ToolNode.invoke`` needs the graph's run config, so it is hosted in a
    throwaway graph; a real ``ToolNode`` is the node, and its own output
    (``{"messages": [...]}``) is what is returned.
    """

    def tools(state):
        return {"out": node.invoke(state["calls"])}

    graph = StateGraph(_FakeState)
    graph.add_node("tools", tools)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile().invoke({"calls": calls})["out"]["messages"]


@pytest.mark.unit
def test_executed_calls_are_accepted_by_a_real_tool_node():
    schemas = {
        tool_.name: tool_.tool_call_schema.model_json_schema()
        for tool_ in (_fake_quote, _fake_rsi)
    }
    context = _context(schemas=schemas, vendor_chains={})
    calls = [
        _call("call-a", "_fake_quote", symbol="AAPL", start_date="2026-08-01",
              end_date="2026-08-14"),
        _call("call-b", "_fake_rsi", symbol="AAPL", indicator="rsi",
              curr_date="2026-08-14"),
    ]
    plan = tg.plan_tool_round(_scope(), calls, tg.ToolLimits(max_rounds=2, max_calls=4),
                              context=context)
    assert plan.executed_call_ids == ("call-a", "call-b")

    # Exactly what a caller would do: hand ``executed_calls`` to ToolNode.
    messages = _run_in_a_real_graph(ToolNode([_fake_quote, _fake_rsi]),
                                    list(plan.executed_calls))

    assert [m.tool_call_id for m in messages] == ["call-a", "call-b"]
    assert all(isinstance(m, ToolMessage) for m in messages)
    assert "quote AAPL" in messages[0].content
    assert "rsi for AAPL" in messages[1].content


@pytest.mark.unit
def test_executed_calls_match_an_ai_message_batch():
    # The real analyst path: the ids come from an AIMessage's tool_calls.
    schemas = {_fake_quote.name: _fake_quote.tool_call_schema.model_json_schema()}
    context = _context(schemas=schemas, vendor_chains={})
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {"name": "_fake_quote", "args": {"symbol": "MSFT",
                                             "start_date": "2026-08-01",
                                             "end_date": "2026-08-14"},
             "id": "call-1", "type": "tool_call"},
            {"name": "_fake_quote", "args": {"symbol": "NVDA",
                                             "start_date": "2026-08-01",
                                             "end_date": "2026-08-14"},
             "id": "call-2", "type": "tool_call"},
        ],
    )
    plan = tg.plan_tool_round(_scope(), ai_message.tool_calls,
                              tg.ToolLimits(max_rounds=2, max_calls=4), context=context)
    assert plan.executed_call_ids == ("call-1", "call-2")

    messages = _run_in_a_real_graph(ToolNode([_fake_quote]), list(plan.executed_calls))
    assert [m.tool_call_id for m in messages] == ["call-1", "call-2"]


# ---------------------------------------------------------------------------
# Resuming and replaying: the recorded outcome is never lost or upgraded
# ---------------------------------------------------------------------------

REAL_ROWS = "REAL_ROWS:| date | close |\n| 2026-08-14 | 201.50 |"


def _cache_one(scope, limits, text=REAL_ROWS, call=STOCK):
    """Plan + start + record one confirmed success; returns (scope, plan)."""
    plan = _plan(scope, [call], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = tg.record_tool_result(
        scope, tool_call_id=call["id"], tool_name=call["name"],
        fingerprint=plan.execute[0]["fingerprint"], result=text,
        cacheable_success=True,
    )
    return scope, plan


@pytest.mark.unit
def test_reuse_plan_resumed_before_its_own_result_keeps_the_original_content():
    limits = tg.ToolLimits(max_rounds=10, max_calls=10)
    scope, _ = _cache_one(_scope(), limits)

    # Round 2: same request, new id -> reuse.
    second = _plan(scope, [dict(STOCK, id="c2")], limits)
    assert [e["action"] for e in second.reuse] == ["reuse"]
    scope = tg.record_round_start(scope, second, limits)
    assert "c2" not in scope["results"]      # its result was never recorded

    # Resume round 2 before any result is saved.
    resumed = _plan(scope, [dict(STOCK, id="c2")], limits, dispatched=True)
    assert resumed.mode == "replay"
    assert resumed.executed_calls == ()       # the tool is never called again
    (message,) = resumed.messages
    assert message["tool_call_id"] == "c2"    # the *current* call id
    assert REAL_ROWS in message["content"]    # the real content, not empty
    assert message["content"].strip() != ""
    assert "status" not in message            # a success carries no error status
    (entry,) = resumed.reuse
    assert entry["action"] == "reuse"
    assert entry["source_tool_call_id"] == "c1"
    assert entry["source"]["text"] == REAL_ROWS


@pytest.mark.unit
def test_resuming_a_reuse_round_does_not_charge_again_or_execute():
    limits = tg.ToolLimits(max_rounds=2, max_calls=2)
    scope, _ = _cache_one(_scope(), limits)
    second = _plan(scope, [dict(STOCK, id="c2")], limits)
    scope = tg.record_round_start(scope, second, limits)
    before = {key: scope[key] for key in ("rounds", "requested", "executed", "reused", "blocked")}

    resumed = _plan(scope, [dict(STOCK, id="c2")], limits, dispatched=True)
    after = tg.record_round_start(scope, resumed, limits)

    assert after is scope                                   # nothing more is charged
    assert {key: after[key] for key in before} == before
    assert resumed.executed == 0                            # nothing really runs
    assert resumed.rounds == 0


@pytest.mark.unit
def test_mixed_partial_execute_and_unrecorded_reuse_resume():
    limits = tg.ToolLimits(max_rounds=10, max_calls=10)
    scope, _ = _cache_one(_scope(), limits)

    # Round 2 mixes a reuse (STOCK, new id) with a real execution (Rsi).
    calls = [dict(STOCK, id="c2"), Rsi]
    second = _plan(scope, calls, limits)
    assert [e["id"] for e in second.reuse] == ["c2"]
    assert second.executed_call_ids == ("r1",)
    scope = tg.record_round_start(scope, second, limits)

    # Rsi finishes; the reuse was never recorded.
    scope = _record(scope, second.execute[0], {"cacheable_success": True, "result": "RSI=61"})

    resumed = _plan(scope, calls, limits, dispatched=True)
    assert resumed.mode == "replay"
    assert resumed.executed_calls == ()
    by_id = {m["tool_call_id"]: m for m in resumed.messages}
    assert set(by_id) == {"c2", "r1"}
    assert REAL_ROWS in by_id["c2"]["content"]       # reuse content survived
    assert by_id["r1"]["content"] == "RSI=61"        # the execute's own result
    # The governance outcome is recorded, never put on the message.
    assert "status" not in by_id["r1"]
    assert scope["results"]["r1"]["status"] == tg.CACHEABLE_SUCCESS


@pytest.mark.unit
@pytest.mark.parametrize(
    "result_kwargs, expected_status, expected_text, label",
    [
        ({"result": "rows 1..2", "cacheable_success": True},
         tg.CACHEABLE_SUCCESS, "rows 1..2", "succeeded"),
        ({"result": ToolMessage(content="BOOM: upstream 500", tool_call_id="x",
                                status="error"), "cacheable_success": True},
         tg.ERROR, "BOOM: upstream 500", "succeeded"),
        ({"result": "NO_DATA_AVAILABLE: nothing for this window"},
         tg.MISSING_DATA, "NO_DATA_AVAILABLE: nothing for this window", "succeeded"),
        ({"result": "DATA_UNAVAILABLE: chain exhausted"},
         tg.DEGRADED, "DATA_UNAVAILABLE: chain exhausted", "succeeded"),
    ],
)
def test_a_completed_call_replays_its_own_status_and_content(
    result_kwargs, expected_status, expected_text, label
):
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    plan = _plan(_scope(), [STOCK], limits)
    scope = tg.record_round_start(_scope(), plan, limits)
    scope = tg.record_tool_result(
        scope, tool_call_id="c1", tool_name="get_stock_data",
        fingerprint=plan.execute[0]["fingerprint"], **result_kwargs,
    )
    assert scope["results"]["c1"]["status"] == expected_status

    replay = _plan(scope, [STOCK], limits)
    assert replay.mode == "replay"
    assert replay.executed_calls == ()          # an error is never re-run
    (message,) = replay.messages
    assert message["tool_call_id"] == "c1"
    assert message["content"] == expected_text   # verbatim, no success note appended
    assert label not in message["content"]
    if expected_status == tg.ERROR:
        assert message["status"] == "error"
    else:
        # Governance outcomes are recorded, never put on a message: a
        # ``ToolMessage`` only accepts ``success`` and ``error``.
        assert "status" not in message


@pytest.mark.unit
def test_replay_survives_a_json_round_trip():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = tg.record_tool_result(
        scope, tool_call_id="c1", tool_name="get_stock_data",
        fingerprint=plan.execute[0]["fingerprint"],
        result=ToolMessage(content="BOOM: upstream 500", tool_call_id="c1",
                           status="error"),
    )
    # Everything the module stores is plain data: a JSON trip must lose nothing.
    reloaded = json.loads(json.dumps(scope))

    replay = _plan(reloaded, [STOCK], limits)
    assert replay.mode == "replay"
    (message,) = replay.messages
    assert message["tool_call_id"] == "c1"
    assert message["content"] == "BOOM: upstream 500"
    assert message["status"] == "error"

    # The same for a registered reuse round restored before its own result.
    limits = tg.ToolLimits(max_rounds=10, max_calls=10)
    scope, _ = _cache_one(_scope(), limits)
    second = _plan(scope, [dict(STOCK, id="c2")], limits)
    scope = tg.record_round_start(scope, second, limits)
    resumed = _plan(json.loads(json.dumps(scope)), [dict(STOCK, id="c2")], limits,
                    dispatched=True)
    (message,) = resumed.messages
    assert message["tool_call_id"] == "c2"
    assert REAL_ROWS in message["content"]


@pytest.mark.unit
def test_errors_are_never_put_in_the_success_cache():
    limits = tg.ToolLimits(max_rounds=5, max_calls=5)
    scope = _scope()
    plan = _plan(scope, [STOCK], limits)
    scope = tg.record_round_start(scope, plan, limits)
    scope = tg.record_tool_result(
        scope, tool_call_id="c1", tool_name="get_stock_data",
        fingerprint=plan.execute[0]["fingerprint"], result="BOOM", raised=True,
        cacheable_success=True,      # a caller cannot promote an error to success
    )
    assert scope["cache"] == {}
    assert scope["results"]["c1"]["status"] == tg.ERROR
    # A later, identical *new* request cannot be served from the cache.
    again = _plan(scope, [dict(STOCK, id="c2")], limits)
    assert again.executed_calls == ()
    assert again.block[0]["reason"] == tg.BLOCK_DUPLICATE_FAILED


# ---------------------------------------------------------------------------
# The execution adapter: a planned round through a real ToolNode
# ---------------------------------------------------------------------------
# Local fake tools and a throwaway graph only: no model, no network. The real
# ``ToolNode`` runs inside a graph because that is the only place where it can
# read graph state (``InjectedState``) and the run config.

_CALLS: list = []


@tool
def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Return a canned quote for one symbol."""
    _CALLS.append(("quote", symbol, {"start_date": start_date, "end_date": end_date}))
    return f"quote {symbol} {start_date}..{end_date}"


@tool
def get_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Return a canned indicator value."""
    _CALLS.append(("indicator", symbol, {"curr_date": curr_date}))
    return f"{indicator} for {symbol} on {curr_date}"


@tool
def get_verified_market_snapshot(symbol: str, start_date: str, end_date: str) -> str:
    """Return the router's absence marker."""
    _CALLS.append(("absent", symbol, {}))
    return f"NO_DATA_AVAILABLE: no rows for {symbol}"


@tool
def _adapter_needs_date(
    symbol: str,
    trade_date: Annotated[str, InjectedState("trade_date")],
) -> str:
    """Require the run date the graph injects."""
    _CALLS.append(("needs_date", symbol, {"trade_date": trade_date}))
    return f"{symbol} run date {trade_date or 'NONE'}"


@tool
def _adapter_optional_date(
    symbol: str,
    trade_date: Annotated[str, InjectedState("trade_date")] = "optional-not-set",
) -> str:
    """Ask for the run date, but do not require it (a defaulted injection)."""
    _CALLS.append(("optional_date", symbol, {"trade_date": trade_date}))
    return f"{symbol} optional date {trade_date}"


@tool
def get_macro_indicators(kind: str) -> str:
    """Raise the exception named by ``kind``."""
    from tradingagents.dataflows.errors import (
        VendorAuthenticationError,
        VendorNotConfiguredError,
    )

    _CALLS.append(("raises", kind, {}))
    if kind == "auth":
        raise VendorAuthenticationError("key rejected")
    if kind == "config":
        raise VendorNotConfiguredError("no vendor configured")
    if kind == "interrupt":
        raise GraphBubbleUp("cancelled")
    if kind == "cancel":
        raise asyncio.CancelledError("cancelled")
    raise RuntimeError("internal bug")


class _CountingNode:
    """A test *runner* wrapping a real ``ToolNode``; records each dispatch.

    It follows the adapter's runner protocol -- ``invoke(node, calls, *,
    state=, config=)`` -- and changes nothing else: the wrapped node runs
    inside the adapter's own minimal graph, exactly like the default path.
    """

    def __init__(self, node):
        self.node = node
        self.batches: list = []
        self.states: list = []

    def invoke(self, node, calls, *, state=None, config=None):
        self.batches.append(copy.deepcopy(calls))
        self.states.append(copy.deepcopy(state))
        return tg.run_tool_node_in_graph(node, calls, state=state, config=config)


class _DateAddingNode:
    """A test *runner* for a node mounted inside the run graph.

    The real graph already carries ``trade_date`` in its channels; this runner
    only needs the run state and config from the adapter to give them to the
    wrapped node.
    """

    def __init__(self, node):
        self.node = node
        self.calls: list = []

    def invoke(self, node, calls, *, state=None, config=None):
        self.calls.append(
            (copy.deepcopy(calls), copy.deepcopy(state), copy.deepcopy(config))
        )
        return tg.run_tool_node_in_graph(node, calls, state=state, config=config)


_ADAPTER_TOOLS = (
    get_stock_data,
    get_indicators,
    get_verified_market_snapshot,
    _adapter_needs_date,
    _adapter_optional_date,
    get_macro_indicators,
)


def _adapter_schemas():
    # The fakes reuse real governance tool names so reuse/cache rules apply;
    # ``_adapter_needs_date`` is out of tree, so its schema is registered once.
    tg.register_tool_schema(
        _adapter_needs_date.name,
        _adapter_needs_date.tool_call_schema.model_json_schema(),
    )
    return {
        tool_.name: tool_.tool_call_schema.model_json_schema()
        for tool_ in _ADAPTER_TOOLS
    }


def _confirms_quote(call, message):
    """A stand-in data-quality confirmer for the fake tools (test-only)."""
    return message.get("status") != "error" and "quote " in str(message.get("content"))


def _executor(tools, node=None, *, analyst=ANALYST, run_id=RUN, limits=None,
              confirm=True, runner=None):
    """An executor whose runner defaults to the **public** default."""
    return tg.ToolExecutor(
        tools,
        node=node,
        analyst=analyst,
        run_id=run_id,
        limits=limits or tg.ToolLimits(max_rounds=6, max_calls=10),
        context=_context(analyst=analyst, schemas=_adapter_schemas(), vendor_chains={}),
        runner=runner,
        confirms_success=_confirms_quote if confirm else None,
    )


def _run(executor, state, calls, *, run_state=None, config=None):
    """The two-phase public path: ``prepare`` then ``execute``."""
    prepared = executor.prepare(
        state, calls, run_state=run_state, config=config
    )
    return executor.execute(prepared)


def _governance(execution):
    """The stored governance value from a prepared round / execution."""
    return execution.state[tg.GOVERNANCE_STATE_KEY]


def _state_from(scope, analyst=ANALYST, run_id=RUN):
    """The governance value (``scope`` is the inner per-analyst record)."""
    return tg.with_scope(tg.new_state(run_id), analyst, scope, run_id)


_HOST_RUN_STATE = {"trade_date": TRADE_DATE}
_HOST_CONFIG = {"configurable": {"thread_id": RUN, "checkpoint_ns": "adapter-test"}}


def _host(tools=("get_stock_data", "get_indicators", "get_verified_market_snapshot",
                 "_adapter_needs_date", "_adapter_optional_date",
                 "get_macro_indicators")):
    """A real ``ToolNode`` over the named adapter tools (the default path)."""
    by_name = {tool_.name: tool_ for tool_ in _ADAPTER_TOOLS}
    return ToolNode([by_name[name] for name in tools])


def _quote(call_id, symbol="AAPL"):
    return _call(call_id, "get_stock_data", symbol=symbol,
                 start_date="2026-08-01", end_date="2026-08-14")


def _indicator(call_id, symbol="AAPL"):
    return _call(call_id, "get_indicators", symbol=symbol,
                 indicator="rsi", curr_date="2026-08-14")


@pytest.fixture(autouse=True)
def _reset_calls():
    _CALLS.clear()
    yield
    _CALLS.clear()


@pytest.mark.unit
def test_only_permitted_execute_calls_reach_the_tool_node():
    _CALLS.clear()
    host = _CountingNode(_host())
    executor = _executor([get_stock_data, get_indicators], _host(), runner=host)

    # Prime one confirmed success, so the second batch contains a reuse.
    first = _run(executor, None, [_quote("call-1")])
    assert first.dispatched == ("call-1",)
    assert _CALLS == [("quote", "AAPL", {"start_date": "2026-08-01",
                                         "end_date": "2026-08-14"})]
    assert first.messages[0]["status"] == "success"

    state = _governance(first)
    batch = [
        _quote("call-2"),  # same request -> reuse, not executed
        _indicator("call-3"),  # execute
        _quote("call-4", symbol="MSFT"),  # execute
        # The same request twice in one batch: the first executes, this one is
        # blocked (an identical id twice would abort the whole batch instead).
        _indicator("call-5", symbol="MSFT"),
        _indicator("call-6", symbol="MSFT"),
    ]
    _CALLS.clear()
    result = _run(executor, state, batch)

    assert result.dispatched == ("call-3", "call-4", "call-5")
    assert [m["tool_call_id"] for m in result.messages] == [
        "call-2", "call-3", "call-4", "call-5", "call-6",
    ]
    # Only the execute calls ran; nothing else reached the node.
    assert [entry[0] for entry in _CALLS] == ["indicator", "quote", "indicator"]
    assert [call["id"] for call in host.batches[-1]] == ["call-3", "call-4", "call-5"]

    # The reuse keeps the current id and the recorded content.
    assert "quote AAPL 2026-08-01..2026-08-14" in result.messages[0]["content"]
    assert "reused" in result.messages[0]["content"]
    # The block is answered locally too.
    assert result.messages[4]["tool_call_id"] == "call-6"
    assert "TOOL_GOVERNANCE_BLOCKED" in result.messages[4]["content"]
    assert result.plan.reused == 1 and result.plan.blocked == 1
    assert result.plan.executed == 3


@pytest.mark.unit
def test_a_multiple_call_batch_is_bounded_and_each_call_runs_once():
    host = _CountingNode(_host())
    limits = tg.ToolLimits(max_rounds=6, max_calls=2)
    executor = _executor([get_stock_data, get_indicators], _host(), limits=limits,
                         runner=host)

    batch = [_quote("c-1"), _quote("c-2", "MSFT"), _quote("c-3", "NVDA")]
    result = _run(executor, None, batch)

    assert result.dispatched == ("c-1", "c-2")
    assert result.plan.executed == 2 and result.plan.blocked == 1
    assert result.plan.block_reasons["c-3"] == tg.BLOCK_CALL_LIMIT
    assert len(host.batches) == 1
    assert [call["id"] for call in host.batches[0]] == ["c-1", "c-2"]
    assert len(_CALLS) == 2
    assert result.scope["executed"] == 2


@pytest.mark.unit
def test_prepare_registers_the_round_before_any_tool_runs():
    # The public two-phase path: ``prepare`` on the *default* node factory, with
    # no node and no state injected. Registration is visible to the caller and
    # nothing has run yet.
    executor = _executor([get_stock_data])
    calls = [_quote("call-1"), _quote("call-2", "MSFT")]

    prepared = executor.prepare(None, calls)

    assert _CALLS == []
    assert prepared.pending == ("call-1", "call-2")
    stored = prepared.state[tg.GOVERNANCE_STATE_KEY]
    record = stored["analysts"][ANALYST]
    # Charged and planned, but no call has a result yet.
    assert record["rounds"] == 1
    assert record["results"] == {}
    assert stored["run_id"] == RUN

    execution = executor.execute(prepared)
    assert [entry[0] for entry in _CALLS] == ["quote", "quote"]
    assert execution.dispatched == ("call-1", "call-2")
    assert execution.scope["results"].keys() == {"call-1", "call-2"}


@pytest.mark.unit
def test_current_call_id_and_injected_run_date_reach_the_tool():
    # The public path: no node (the executor builds a real ``ToolNode``), the
    # default runner, and the *real run state* handed in explicitly.
    executor = _executor([get_stock_data, _adapter_needs_date])

    result = _run(
        executor,
        None,
        [
            _call("call-1", "_adapter_needs_date", symbol="AAPL"),
            _call("call-2", "_adapter_needs_date", symbol="MSFT"),
        ],
        run_state={"trade_date": TRADE_DATE},
        config=_HOST_CONFIG,
    )

    assert [m["tool_call_id"] for m in result.messages] == ["call-1", "call-2"]
    # ``langchain_core`` marks a finished, non-error ``ToolMessage`` "success".
    assert [m["status"] for m in result.messages] == ["success", "success"]
    assert all(m["type"] == "tool" for m in result.messages)
    assert result.messages[0]["content"] == f"AAPL run date {TRADE_DATE}"
    assert result.messages[1]["content"] == f"MSFT run date {TRADE_DATE}"
    # The tool saw the injected date; the model's call did not carry it.
    assert _CALLS == [
        ("needs_date", "AAPL", {"trade_date": TRADE_DATE}),
        ("needs_date", "MSFT", {"trade_date": TRADE_DATE}),
    ]


@pytest.mark.unit
def test_a_missing_run_date_refuses_before_anything_starts():
    # ``ToolContext`` names a trade date, but it is a fingerprint input only:
    # with no real run state the tool must not run on an empty date.
    executor = _executor([get_stock_data, _adapter_needs_date, _adapter_optional_date])
    host = _CountingNode(_host(tools=("_adapter_needs_date",)))
    host_executor = _executor([_adapter_needs_date], _host(tools=("_adapter_needs_date",)),
                              runner=host)
    calls = [_call("call-1", "_adapter_needs_date", symbol="AAPL")]

    for run in (executor, host_executor):
        with pytest.raises(tg.GovernanceStateError, match="trade_date"):
            _run(run, None, calls)
    assert _CALLS == []
    assert host.batches == []

    # A real state without the field, or with a blank one, is no better.
    with pytest.raises(tg.GovernanceStateError, match="trade_date"):
        _run(executor, None, calls, run_state={"messages": []})
    with pytest.raises(tg.GovernanceStateError, match="trade_date"):
        _run(executor, None, calls, run_state={"trade_date": ""})
    assert _CALLS == []

    # A prepared round is checked again at ``execute``: overriding the run
    # state with one that lacks the date refuses there too, nothing dispatched.
    prepared = executor.prepare(None, calls, run_state={"trade_date": TRADE_DATE})
    with pytest.raises(tg.GovernanceStateError, match="trade_date"):
        executor.execute(prepared, run_state={})
    assert _CALLS == []

    # The runner never invents a value the run did not carry: with no date the
    # declared field is simply absent (and the tool keeps its own default); the
    # executor is what refuses a *required* one above.
    node = ToolNode([_adapter_optional_date])
    calls = [_call("call-1", "_adapter_optional_date", symbol="AAPL")]
    output = tg.run_tool_node_in_graph(node, calls, state={})
    assert output["messages"][0].content == "AAPL optional date optional-not-set"
    _CALLS.clear()

    # A tool that only *optionally* asks for the date is not blocked, and it
    # never sees a date the run did not carry.
    optional = _run(
        executor, None, [_call("call-2", "_adapter_optional_date", symbol="AAPL")]
    )
    assert optional.dispatched == ("call-2",)
    assert _CALLS == [
        ("optional_date", "AAPL", {"trade_date": "optional-not-set"}),
    ]


@pytest.mark.unit
def test_the_run_is_handed_to_the_node_and_a_caller_cannot_skip_it():
    # A node mounted inside the real graph (as production mounts it) gets the
    # run state and config through the runner, unchanged.
    mounted = _DateAddingNode(_host(tools=("_adapter_needs_date",)))
    executor = _executor([_adapter_needs_date], runner=mounted)

    run_state = {"trade_date": TRADE_DATE, "company_of_interest": "AAPL"}
    result = _run(
        executor,
        None,
        [_call("call-1", "_adapter_needs_date", symbol="AAPL")],
        run_state=run_state,
        config=_HOST_CONFIG,
    )

    assert result.messages[0]["content"] == f"AAPL run date {TRADE_DATE}"
    assert mounted.calls[-1][1] == run_state
    # The caller's config arrives unchanged (``thread_id`` and everything else).
    for key, value in _HOST_CONFIG.items():
        assert mounted.calls[-1][2][key] == value

    # A node that cannot be handed the run state is refused, never run blind.
    class _BlindNode:
        def invoke(self, calls):  # no state/config parameters
            raise AssertionError("must not run")

    blind = _executor([_adapter_needs_date], _BlindNode())
    with pytest.raises(tg.GovernanceStateError, match="node"):
        _run(blind, None, [_call("call-2", "_adapter_needs_date", symbol="MSFT")])
    assert _CALLS == [("needs_date", "AAPL", {"trade_date": TRADE_DATE})]


@pytest.mark.unit
def test_the_default_node_factory_runs_a_real_graph():
    # The public path with *nothing* injected: no node, no runner, no state.
    # ``ToolExecutor`` must build a real ``ToolNode`` and host it in a graph.
    executor = tg.ToolExecutor(
        [get_stock_data],
        analyst=ANALYST,
        run_id=RUN,
        limits=tg.ToolLimits(max_rounds=6, max_calls=10),
        context=_context(schemas=_adapter_schemas(), vendor_chains={}),
    )
    assert executor._node is None

    execution = _run(executor, None, [_quote("call-1")])

    from langgraph.prebuilt import ToolNode

    assert isinstance(executor._node, ToolNode)
    assert execution.dispatched == ("call-1",)
    assert execution.messages[0]["content"] == "quote AAPL 2026-08-01..2026-08-14"
    assert [entry[0] for entry in _CALLS] == ["quote"]
    assert execution.scope["results"]["call-1"]["status"] == tg.UNKNOWN


@pytest.mark.unit
def test_an_error_status_is_recorded_as_an_error_and_never_cached():
    executor = _executor([get_verified_market_snapshot])

    result = _run(
        executor,
        None,
        [_call("call-1", "get_verified_market_snapshot", symbol="AAPL",
               start_date="2026-08-01", end_date="2026-08-14")],
    )

    assert result.messages[0]["tool_call_id"] == "call-1"
    assert "NO_DATA_AVAILABLE" in result.messages[0]["content"]
    assert result.scope["results"]["call-1"]["status"] == tg.MISSING_DATA
    assert result.scope.get("cache") in (None, {})

    # A repeat through a *different* analyst is refused before anything runs:
    # permission is the binding, not the governance schema.
    _CALLS.clear()
    other_analyst = _executor([get_stock_data], analyst="news")
    with pytest.raises(tg.GovernanceBatchError):
        other_analyst.prepare(
            _governance(result),
            [_call("call-2", "get_verified_market_snapshot", symbol="AAPL",
                   start_date="2026-08-01", end_date="2026-08-14")],
        )
    assert _CALLS == []

    # The same analyst and run: an identical request already failed, so it is
    # blocked, not executed again.
    same = _executor([get_verified_market_snapshot])
    again = _run(
        same,
        _governance(result),
        [_call("call-3", "get_verified_market_snapshot", symbol="AAPL",
               start_date="2026-08-01", end_date="2026-08-14")],
    )
    assert again.dispatched == ()
    assert _CALLS == []
    assert again.plan.block_reasons["call-3"] == tg.BLOCK_DUPLICATE_FAILED
    # A block never claims a status the outcome did not have.
    assert again.messages[0].get("status") != "success"


@pytest.mark.unit
def test_a_resume_runs_only_the_remainder_and_a_replay_runs_nothing():
    host = _CountingNode(_host())
    executor = _executor([get_stock_data, get_indicators], _host(), runner=host)
    calls = [_quote("call-1"), _indicator("call-2")]

    # The round is registered by the adapter itself; the "crash" is the
    # `commit` never happening. The caller keeps `prepared.state`, nothing
    # runs, and no record is rebuilt by hand.
    prepared = executor.prepare(None, calls)
    assert prepared.state[tg.GOVERNANCE_STATE_KEY]["analysts"][ANALYST]["rounds"] == 1
    assert _CALLS == [] and host.batches == []

    resumed = executor.prepare(prepared.state[tg.GOVERNANCE_STATE_KEY], calls)
    assert isinstance(resumed, tg.PreparedRound)
    resumed = executor.execute(resumed)
    assert resumed.plan.mode == "resume"
    assert resumed.dispatched == ("call-1", "call-2")
    assert len(_CALLS) == 2
    assert resumed.scope["rounds"] == 1  # the round is not charged twice

    # Once every call has a result the same batch is a replay: nothing runs.
    _CALLS.clear()
    replayed = _run(executor, _governance(resumed), calls)
    assert replayed.plan.mode == "replay"
    assert replayed.dispatched == ()
    assert _CALLS == []
    # Only the resume batch reached the node; the replay dispatched nothing.
    assert len(host.batches) == 1
    assert [m["tool_call_id"] for m in replayed.messages] == ["call-1", "call-2"]
    assert "quote AAPL" in replayed.messages[0]["content"]
    assert replayed.messages[0]["content"] == resumed.messages[0]["content"]
    assert replayed.scope["rounds"] == 1
    # A successful replay carries no status: ``success`` is not a governance
    # outcome and the replay never invents one.
    assert "status" not in replayed.messages[0]


@pytest.mark.unit
def test_partial_results_resume_with_only_the_missing_call():
    host = _host()
    executor = _executor([get_stock_data, get_indicators], host)
    calls = [_quote("call-1"), _quote("call-2", symbol="MSFT")]

    first = _run(executor, None, calls)
    assert [m["tool_call_id"] for m in first.messages] == ["call-1", "call-2"]

    # Pretend only call-1 produced a result (as if the batch had been
    # interrupted part-way): the first execution recorded both, so call-2's
    # result and its cache entry are removed.
    partial = copy.deepcopy(first.scope)
    partial["results"].pop("call-2", None)
    for fingerprint, entry in list((partial.get("cache") or {}).items()):
        if entry.get("entry", {}).get("tool_call_id") == "call-2":
            del partial["cache"][fingerprint]

    _CALLS.clear()
    resumed = _run(executor, _state_from(partial), calls)
    assert resumed.plan.mode == "resume"
    assert resumed.dispatched == ("call-2",)
    assert [entry[0] for entry in _CALLS] == ["quote"]
    assert [m["tool_call_id"] for m in resumed.messages] == ["call-1", "call-2"]
    assert "quote AAPL" in resumed.messages[0]["content"]
    assert "quote MSFT" in resumed.messages[1]["content"]
    assert resumed.scope["rounds"] == 1


@pytest.mark.unit
def test_same_analyst_same_run_isolation_and_different_analyst_permission():
    host = _host()
    limits = tg.ToolLimits(max_rounds=6, max_calls=10)
    # Both analysts may call ``get_stock_data`` (the real news analyst is bound
    # to several tools); the news analyst additionally has ``get_indicators``.
    market = _executor([get_stock_data], host, analyst="market", limits=limits)
    news = _executor([get_stock_data, get_indicators], host, analyst="news",
                     limits=limits)
    other_run = tg.ToolExecutor(
        [get_stock_data],
        node=host,
        analyst="market",
        run_id="run-2",
        limits=limits,
        context=_context(run_id="run-2", schemas=_adapter_schemas(), vendor_chains={}),
        confirms_success=_confirms_quote,
    )

    base = _run(market, None, [_quote("call-1")])
    state = _governance(base)

    # The same analyst and run answers the repeat without running it.
    _CALLS.clear()
    same = _run(market, state, [_quote("call-2")])
    assert same.dispatched == ()
    assert _CALLS == []

    # Different analyst, same run: the request is not the market analyst's
    # evidence, so it is executed rather than reused.
    _CALLS.clear()
    news_result = _run(news, state, [_quote("call-9")])
    assert news_result.dispatched == ("call-9",)
    assert [entry[0] for entry in _CALLS] == ["quote"]

    # Same analyst, different run: also not shared.
    _CALLS.clear()
    other = _run(other_run, state, [_quote("call-7")])
    assert other.dispatched == ("call-7",)
    assert [entry[0] for entry in _CALLS] == ["quote"]

    # A tool the analyst is not bound to is refused before anything runs.
    _CALLS.clear()
    with pytest.raises(tg.GovernanceBatchError):
        _run(market, state, [_indicator("call-3")])
    assert _CALLS == []


@pytest.mark.unit
def test_governance_knowing_a_tool_does_not_grant_permission():
    # ``get_news`` has a governance schema, but this analyst is not bound to it.
    assert tg.tool_schema("get_news") is not None
    executor = _executor([get_stock_data])
    call = _call("call-1", "get_news", ticker="AAPL", start_date="2026-08-01",
                 end_date="2026-08-14")

    with pytest.raises(tg.GovernanceBatchError, match="get_news"):
        executor.prepare(None, [call])
    assert _CALLS == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "kind,error",
    [
        ("auth", "VendorAuthenticationError"),
        ("config", "VendorNotConfiguredError"),
        ("internal", "RuntimeError"),
    ],
)
def test_auth_config_and_internal_errors_propagate_unchanged(kind, error):
    from tradingagents.dataflows import errors

    expected = getattr(errors, error, RuntimeError)
    # The default handler re-raises anything that is not an argument error.
    executor = _executor([get_macro_indicators])

    with pytest.raises(expected):
        _run(executor, None, [_call("call-1", "get_macro_indicators", kind=kind)])

    # The call ran once and produced no message or result.
    assert [entry[0] for entry in _CALLS] == ["raises"]


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["interrupt", "cancel"])
def test_interrupts_and_cancellation_are_not_swallowed(kind):
    from langgraph.errors import NodeCancelledError

    executor = _executor([get_macro_indicators])

    # ``GraphBubbleUp`` reaches the caller as itself. In a *sync* graph a
    # ``CancelledError`` raised by the node body is re-raised by langgraph as
    # ``NodeCancelledError`` (it is never treated as a silent tear-down); the
    # adapter does not catch or convert either.
    raised = GraphBubbleUp if kind == "interrupt" else NodeCancelledError
    with pytest.raises(raised):
        _run(executor, None, [_call("call-1", "get_macro_indicators", kind=kind)])
    assert [entry[0] for entry in _CALLS] == ["raises"]


@pytest.mark.unit
def test_a_raising_tool_keeps_the_registration_and_resumes_without_recharging():
    # A real tool raises through the real ``ToolNode`` (uncatchable ``BaseException``
    # subclasses are re-raised by the node). The caller still holds the state the
    # adapter registered, and finishing the batch builds a round from that state
    # alone: the same round (already charged), the same call id, no second charge.
    attempts = {"n": 0}

    @tool
    def _raises_once(symbol: str) -> str:
        """Raise on the first attempt, then answer like a quote."""
        _CALLS.append(("raises_once", symbol, {}))
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise VendorAuthenticationError("key rejected")
        return f"quote {symbol} 2026-08-01..2026-08-14"

    schemas = _adapter_schemas()
    schemas[_raises_once.name] = _raises_once.tool_call_schema.model_json_schema()
    tg.register_tool_schema(
        _raises_once.name, _raises_once.tool_call_schema.model_json_schema()
    )
    executor = tg.ToolExecutor(
        [_raises_once],
        analyst=ANALYST,
        run_id=RUN,
        limits=tg.ToolLimits(max_rounds=6, max_calls=10),
        context=_context(schemas=schemas, vendor_chains={}),
        confirms_success=_confirms_quote,
    )
    first_call = _call("call-1", "_raises_once", symbol="AAPL")

    prepared = executor.prepare(None, [first_call])
    registered = copy.deepcopy(prepared.state[tg.GOVERNANCE_STATE_KEY])
    charged = registered["analysts"][ANALYST]
    assert charged["rounds"] == 1

    # What the caller keeps after the crash is the *stored* state.
    stored = copy.deepcopy(prepared.state[tg.GOVERNANCE_STATE_KEY])
    with pytest.raises(VendorAuthenticationError):
        executor.execute(prepared)
    assert stored == registered
    assert stored["analysts"][ANALYST]["results"] == {}
    assert [entry[0] for entry in _CALLS] == ["raises_once"]

    # After a restart, a new executor resumes from the stored state: the round
    # and the call allowance are already spent and are not spent again.
    restarted = _executor([_raises_once])
    resumed_round = restarted.prepare(stored, [first_call])
    assert resumed_round.plan.mode == "resume"
    resumed = restarted.execute(resumed_round)
    assert resumed.plan.mode == "resume"
    assert resumed.dispatched == ("call-1",)
    after = stored["analysts"][ANALYST]
    assert after["rounds"] == charged["rounds"]  # charged once, not twice
    assert after["executed"] == charged["executed"]
    assert resumed.scope["rounds"] == charged["rounds"]
    assert resumed.scope["executed"] == charged["executed"]
    assert "quote AAPL 2026-08-01..2026-08-14" in resumed.messages[0]["content"]
    assert [entry[0] for entry in _CALLS] == ["raises_once", "raises_once"]

    # Only ``prepare`` returns the registration; a batch is never executed
    # without one (``execute`` accepts nothing but a ``PreparedRound``).
    assert not isinstance(stored, tg.PreparedRound)
    with pytest.raises(TypeError, match="PreparedRound"):
        executor.execute(stored)


@pytest.mark.unit
def test_the_one_step_form_is_gone():
    # ``execute(state, calls)`` cannot hand back the registration when a tool
    # raises, so it does not exist: a round is only ever executed via
    # ``prepare``. Nothing is planned or charged by the rejected call.
    executor = _executor([get_stock_data])
    frozen = {"version": tg.SCHEMA_VERSION, "run_id": RUN, "analysts": {}}
    before = copy.deepcopy(frozen)

    with pytest.raises(TypeError):
        executor.execute(frozen, [_quote("call-1")])

    assert frozen == before
    assert _CALLS == []


@pytest.mark.unit
def test_a_failed_registration_runs_zero_tools():
    # The caller cannot keep the registration, so it must be able to abort
    # before any tool starts: the save happens between prepare and execute.
    # The one-step form is gone: registering is always ``prepare``, and an
    # unusable batch fails there, before a round is even charged.
    executor = _executor([get_stock_data])
    calls = [_quote("call-1"), _quote("call-2", "MSFT")]
    store: dict = {}

    def save(state):
        raise OSError("state store unavailable")

    prepared = executor.prepare(None, calls)
    with pytest.raises(OSError):
        save(prepared.state)
    assert _CALLS == []
    assert store == {}
    # The prepared round is still a *pending* registration, and nothing of it
    # reached the tools.
    assert prepared.pending == ("call-1", "call-2")

    # An unusable batch aborts the same way: refused at ``prepare``, and the
    # state it was given is not even charged.
    frozen = {"version": tg.SCHEMA_VERSION, "run_id": RUN, "analysts": {}}
    before = copy.deepcopy(frozen)
    with pytest.raises(tg.GovernanceBatchError):
        executor.prepare(frozen, [_call("call-1", "get_news", ticker="AAPL")])
    assert frozen == before
    assert _CALLS == []


@pytest.mark.unit
@pytest.mark.parametrize("order", [("market", "news"), ("news", "market")])
def test_scope_is_the_analysts_own_record_whatever_the_insertion_order(order):
    # Both analysts are bound to ``get_stock_data``, as in production. Each
    # execution must report *its own* record, never the first one in the state.
    state = tg.new_state(RUN)
    records = {}
    for analyst in order:
        runner = _executor([get_stock_data, get_indicators],
                           _host(tools=("get_stock_data", "get_indicators")),
                           analyst=analyst)
        calls = (
            [_quote("q-1")]
            if analyst == "market"
            else [_quote("n-1"), _indicator("n-2")]
        )
        execution = _run(runner, state, calls)
        state = _governance(execution)
        records[analyst] = execution.scope
        # The record is read by this analyst's name, not by position.
        assert execution.analyst == analyst
        assert execution.scope == state["analysts"][analyst]
        assert set(execution.scope["results"]) == {call["id"] for call in calls}

    assert list(state["analysts"]) == list(order)
    assert set(records["market"]["results"]) == {"q-1"}
    assert set(records["news"]["results"]) == {"n-1", "n-2"}
    assert records["market"]["outcomes"][tg.CACHEABLE_SUCCESS] == 1
    assert records["news"]["outcomes"][tg.CACHEABLE_SUCCESS] == 1

    # Re-running the analyst written *first* still reports that analyst's
    # record (it was the one a positional lookup would have got wrong once the
    # second record exists, and vice versa).
    first = order[0]
    second = order[1]
    later = "n-1" if second == "news" else "q-1"
    again = _run(
        _executor([get_stock_data], analyst=first), state,
        [_quote(f"{first}-again", symbol="MSFT")],
    )
    assert again.scope == _governance(again)["analysts"][first]
    assert f"{first}-again" in again.scope["results"]
    assert later not in again.scope["results"]
    assert again.scope["results"][f"{first}-again"]["status"] == tg.CACHEABLE_SUCCESS

    # An analyst with no record never borrows another one's (``commit`` reads
    # back the stored record by name).
    absent = _executor([get_stock_data], analyst="social")
    prepared = absent.prepare(state, [_quote("s-1")])
    assert prepared.state[tg.GOVERNANCE_STATE_KEY]["analysts"]["social"]["rounds"] == 1
    execution = absent.execute(prepared)
    assert set(execution.scope["results"]) == {"s-1"}
    assert execution.scope == _governance(execution)["analysts"]["social"]


@pytest.mark.unit
def test_success_and_error_replays_survive_json_and_real_messages():
    # The node hosts ``get_stock_data`` only, so the valid ``get_indicators``
    # call below is an unknown tool *to the node*: its handler answers with a
    # ``status="error"`` message (the first call is a real success).
    host = _host(tools=("get_stock_data",))
    executor = _executor([get_stock_data, get_indicators], host)

    first = _run(executor, None, [_quote("call-1")])
    assert first.messages[0]["status"] == "success"
    error_call = _indicator("call-2")
    error = _run(executor, _governance(first), [error_call])
    messages = [*first.messages, *error.messages]
    assert [m["status"] for m in messages] == ["success", "error"]

    # Save -> JSON round-trip -> replay of each round's own batch.
    saved = json.loads(json.dumps(_governance(error)))
    replayed1 = _run(executor, saved, [_quote("call-1")])
    replayed2 = _run(executor, saved, [error_call])

    assert replayed1.dispatched == () and replayed2.dispatched == ()
    replayed = [*replayed1.messages, *replayed2.messages]
    assert [m["tool_call_id"] for m in replayed] == ["call-1", "call-2"]
    # The replay never puts a governance outcome on a message: the success
    # carries no status, the error keeps its legal "error".
    assert "status" not in replayed[0]
    assert replayed[1]["status"] == "error"
    assert replayed[0]["content"] == messages[0]["content"]
    assert replayed[1]["content"] == messages[1]["content"]

    # Each replay message is accepted by the real message type, which reports
    # a status-less success as "success" and keeps the error ...
    real = [ToolMessage(**m) for m in replayed]
    assert [msg.status for msg in real] == ["success", "error"]

    # ... and the message channel accepts it (an AI call followed by both
    # answers is a legal conversation).
    merged = [AIMessage(content="", tool_calls=[
        {"id": "call-1", "name": "get_stock_data", "args": {}},
        {"id": "call-2", "name": "get_stock_data", "args": {}},
    ]), *real]
    graph = StateGraph(_MergeState)
    graph.add_node("add", lambda state: {})
    graph.add_edge(START, "add")
    graph.add_edge("add", END)
    merged_state = graph.compile().invoke({"messages": merged})

    assert [type(m).__name__ for m in merged_state["messages"]] == [
        "AIMessage", "ToolMessage", "ToolMessage",
    ]
    assert [m.status for m in merged_state["messages"][1:]] == ["success", "error"]
    assert merged_state["messages"][2].content == replayed[1]["content"]


class _MergeState(TypedDict, total=False):
    messages: Annotated[list, lambda left, right: [*left, *right]]


@pytest.mark.unit
def test_unconfirmed_text_is_never_cached_but_a_confirmed_result_is():
    # A non-empty string with status="success" is *not* evidence of valid data.
    unconfirmed = _executor([get_stock_data], confirm=False)
    first = _run(unconfirmed, None, [_quote("call-1")])
    assert first.messages[0]["status"] == "success"
    assert first.messages[0]["content"]
    assert first.scope["results"]["call-1"]["status"] == tg.UNKNOWN
    assert first.scope.get("cache") in (None, {})

    # A different request is executed, not served from a cache of the
    # unconfirmed one.
    declining = _executor([get_stock_data], confirm=False)
    again = _run(declining, _state_from(first.scope), [_quote("call-2", "MSFT")])
    assert again.dispatched == ("call-2",)
    assert again.scope["results"]["call-2"]["status"] == tg.UNKNOWN
    assert again.scope.get("cache") in (None, {})

    # An explicit confirmation from the injected confirmer is what caches it.
    confirmed = _executor([get_stock_data])
    ok = _run(confirmed, None, [_quote("call-1")])
    assert ok.scope["results"]["call-1"]["status"] == tg.CACHEABLE_SUCCESS
    assert len(ok.scope["cache"]) == 1


@pytest.mark.unit
def test_missing_degraded_error_and_unconfirmed_results_are_never_cached():
    @tool
    def degraded_tool(symbol: str) -> str:
        """Return the router's degradation marker."""
        return f"DATA_UNAVAILABLE: stale rows for {symbol}"

    tg.register_tool_schema(
        degraded_tool.name, degraded_tool.tool_call_schema.model_json_schema()
    )

    # The confirmer says "yes" to everything; the classifier must still win.
    always = tg.ToolExecutor(
        [get_verified_market_snapshot, degraded_tool],
        analyst=ANALYST,
        run_id=RUN,
        limits=tg.ToolLimits(max_rounds=6, max_calls=10),
        context=_context(schemas=_adapter_schemas(), vendor_chains={}),
        confirms_success=lambda call, message: True,
    )

    result = _run(
        always,
        None,
        [
            _call("call-1", "get_verified_market_snapshot", symbol="AAPL",
                  start_date="2026-08-01", end_date="2026-08-14"),
            _call("call-2", "degraded_tool", symbol="AAPL"),
        ],
    )
    assert result.scope["results"]["call-1"]["status"] == tg.MISSING_DATA
    assert result.scope["results"]["call-2"]["status"] == tg.DEGRADED
    assert result.scope.get("cache") in (None, {})

    # An error status is never cached either. The node hosts a different tool,
    # so a valid ``get_stock_data`` call is an unknown tool to it: an error.
    error_executor = _executor([get_stock_data], _host(tools=("get_indicators",)))
    error = _run(
        error_executor,
        None,
        [_call("call-3", "get_stock_data", symbol="AAPL",
               start_date="2026-08-01", end_date="2026-08-14")],
    )
    assert error.messages[0]["status"] == "error"
    assert error.scope.get("cache") in (None, {})
    # ``error`` is a legal message status: the real type keeps it.
    assert ToolMessage(**error.messages[0]).status == "error"


@pytest.mark.unit
@pytest.mark.parametrize(
    "batch",
    [
        [],
        "call-1",
        [{"name": "get_stock_data", "args": {}}],
        [{"id": "call-1", "name": "", "args": {}}],
        [_quote("call-1"), _quote("call-1", "MSFT")],
        # A call the tool itself would reject: the whole batch fails loudly.
        [_quote("call-1"), _call("call-2", "get_stock_data", symbol="AAPL")],
    ],
)
def test_an_invalid_batch_fails_before_any_dispatch(batch):
    executor = _executor([get_stock_data])
    frozen = {"version": tg.SCHEMA_VERSION, "run_id": RUN, "analysts": {}}
    before = copy.deepcopy(frozen)

    with pytest.raises(tg.GovernanceBatchError):
        executor.prepare(frozen, batch)

    assert _CALLS == []
    assert frozen == before


@pytest.mark.unit
def test_a_confirmed_success_from_a_reusable_tool_is_cached_and_reused():
    host = _host(tools=("get_stock_data",))
    executor = _executor([get_stock_data], host)
    result = _run(executor, None, [_quote("call-1")])
    status = result.scope["results"]["call-1"]["status"]
    assert status == tg.CACHEABLE_SUCCESS
    # The cache is keyed by the request fingerprint, produced by the same
    # planning step, never invented by the adapter.
    assert list(result.scope["cache"]) == [result.plan.execute[0]["fingerprint"]]

    _CALLS.clear()
    again = _run(executor, _governance(result), [_quote("call-2")])
    assert again.dispatched == ()
    assert [m["tool_call_id"] for m in again.messages] == ["call-2"]
    assert again.plan.reuse[0]["action"] == "reuse"
    assert _CALLS == []
