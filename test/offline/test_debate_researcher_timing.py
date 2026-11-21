"""Offline tests for measured-time researcher accounting and abort semantics.

Pins the binding safety contracts of the DEBT-021 repair:
- an invalid INITIAL clock aborts BEFORE ``llm.invoke`` (no model call made);
- an invalid END clock aborts, persisting unavailable telemetry and a sanitized
  audit entry before raising;
- a normal call records measured elapsed time and provider usage honestly;
- a failed invocation re-raises and writes only an allow-listed audit record.

Traceability: FR-DDT-003 / NFR-BUD-001 / INV-7 (budget safety); NFR-AUD-001 /
INV-6 (sanitized audit). No network, no paid model.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.researchers.bull_researcher import (
    InvalidClockError,
    create_bull_researcher,
)
from tradingagents.debate.budget import record_call_usage
from tradingagents.debate.failure_audit import iter_failure_records

_RECORD = {
    "evidence_id": "run:1",
    "quality_status": "High",
    "observed_at": "2026-05-01",
    "value_raw": "190",
    "metric_name": "close",
    "unit_normalized": "USD",
}
_TURN = (
    "Argument.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; "
    "new_claims=growth|run:1;"
)


def _state(audit_path):
    return {
        "company_of_interest": "COF",
        "trade_date": "2026-05-13",
        "asset_type": "stock",
        "market_report": "m",
        "sentiment_report": "s",
        "news_report": "n",
        "fundamentals_report": "f",
        "data_quality_verdict": "normal",
        "data_quality_evidence_records": [_RECORD],
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "count": 0,
            "turns": [],
        },
        "debate_failure_log_path": str(audit_path),
    }


def _llm(content=_TURN, usage=None):
    llm = MagicMock()
    resp = MagicMock()
    resp.content = content
    resp.usage_metadata = usage
    resp.response_metadata = None
    llm.invoke = MagicMock(return_value=resp)
    return llm


def test_normal_call_records_measured_seconds_and_provider(tmp_path):
    llm = _llm(usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    node = create_bull_researcher(llm, clock=iter([10.0, 10.5]).__next__)
    out = node(_state(tmp_path / "f.jsonl"))
    usage = out["debate_usage"]
    assert usage["seconds"] == 0.5
    assert usage["provenance"]["seconds"] == "measured"
    assert usage["tokens"] == 120
    assert usage["provenance"]["tokens"] == "provider"


def test_invalid_initial_clock_aborts_before_invoke(tmp_path):
    audit = tmp_path / "f.jsonl"
    llm = _llm()
    # First (and only) clock read is invalid -> abort before llm.invoke.
    node = create_bull_researcher(llm, clock=lambda: float("nan"))
    with pytest.raises(InvalidClockError):
        node(_state(audit))
    llm.invoke.assert_not_called()
    records = list(iter_failure_records(audit))
    assert records and records[0]["reason"] == "clock_invalid"
    assert "nan" not in json.dumps(records).lower()


def test_invalid_end_clock_persists_audit_then_raises(tmp_path):
    audit = tmp_path / "f.jsonl"
    llm = _llm()
    # start valid, end invalid (backwards).
    seq = iter([10.0, 5.0])
    node = create_bull_researcher(llm, clock=seq.__next__)
    with pytest.raises(InvalidClockError):
        node(_state(audit))
    llm.invoke.assert_called_once()  # the call happened; end read failed
    records = list(iter_failure_records(audit))
    assert records and records[0]["reason"] == "clock_invalid"


def test_failed_invocation_reraises_and_audits_without_raw_text(tmp_path):
    audit = tmp_path / "f.jsonl"
    llm = MagicMock()
    llm.invoke = MagicMock(side_effect=RuntimeError("SECRET prompt body sk-abc"))
    node = create_bull_researcher(llm, clock=iter([1.0, 2.0]).__next__)
    with pytest.raises(RuntimeError):
        node(_state(audit))
    blob = audit.read_text(encoding="utf-8")
    assert "SECRET" not in blob
    assert "sk-abc" not in blob
    records = list(iter_failure_records(audit))
    assert records and records[0]["speaker"] == "Bull"


def _bear_state(audit_path):
    s = _state(audit_path)
    return s


def test_before_invoke_clock_abort_records_zero_attempted(tmp_path):
    from tradingagents.agents.researchers.bear_researcher import (
        InvalidClockError as BearClockError,
        create_bear_researcher,
    )

    for factory, state_fn, exc in (
        (create_bull_researcher, _state, InvalidClockError),
        (create_bear_researcher, _bear_state, BearClockError),
    ):
        audit = tmp_path / f"{factory.__name__}.jsonl"
        llm = _llm()
        node = factory(llm, clock=lambda: float("inf"))
        with pytest.raises(exc):
            node(state_fn(audit))
        llm.invoke.assert_not_called()
        rec = list(iter_failure_records(audit))[0]
        assert rec["status"] == "clock_abort_before_invoke"
        assert rec["safe_usage"]["calls"] == 0
        assert rec["safe_usage"]["failed_calls"] == 0
        assert rec["safe_usage"]["tokens_source"] == "unavailable"
        assert rec["safe_usage"]["seconds_source"] == "unavailable"
        assert rec["run_id"]  # identity fallback present
        assert "turn_index" in rec["safe_usage"]


def test_invoked_failure_records_one_attempted_call(tmp_path):
    from tradingagents.agents.researchers.bear_researcher import (
        create_bear_researcher,
    )

    for factory, state_fn in (
        (create_bull_researcher, _state),
        (create_bear_researcher, _bear_state),
    ):
        audit = tmp_path / f"{factory.__name__}_fail.jsonl"
        llm = MagicMock()
        llm.invoke = MagicMock(side_effect=RuntimeError("SECRET body sk-XYZ"))
        node = factory(llm, clock=iter([1.0, 2.0]).__next__)
        with pytest.raises(RuntimeError):
            node(state_fn(audit))
        rec = list(iter_failure_records(audit))[0]
        assert rec["status"] == "invoke_failed"
        assert rec["safe_usage"]["calls"] == 1
        assert rec["safe_usage"]["failed_calls"] == 1
        blob = audit.read_text(encoding="utf-8")
        assert "SECRET" not in blob and "sk-XYZ" not in blob
        # No fabricated numeric token/time cost is recorded.
        assert "tokens" not in rec["safe_usage"]
        assert "seconds" not in rec["safe_usage"]
        assert rec["safe_usage"]["tokens_source"] == "unavailable"


def test_invalid_end_clock_records_attempted_unavailable(tmp_path):
    from tradingagents.agents.researchers.bear_researcher import (
        InvalidClockError as BearClockError,
        create_bear_researcher,
    )

    for factory, state_fn, exc in (
        (create_bull_researcher, _state, InvalidClockError),
        (create_bear_researcher, _bear_state, BearClockError),
    ):
        audit = tmp_path / f"{factory.__name__}_endbad.jsonl"
        llm = _llm()
        # start valid, end invalid (backwards).
        node = factory(llm, clock=iter([10.0, 3.0]).__next__)
        with pytest.raises(exc):
            node(state_fn(audit))
        rec = list(iter_failure_records(audit))[0]
        assert rec["status"] == "clock_invalid_after_invoke"
        assert rec["safe_usage"]["calls"] == 1
        assert rec["safe_usage"]["failed_calls"] == 1
        assert rec["safe_usage"]["seconds_source"] == "unavailable"


def test_partial_input_only_missing_output_estimated_from_response_chars():
    # Missing OUTPUT is estimated from response_chars; missing INPUT from
    # prompt_chars. Not an arbitrary halving of combined length.
    from types import SimpleNamespace

    from tradingagents.debate.budget import extract_provider_usage

    pu = extract_provider_usage(
        SimpleNamespace(usage_metadata={"input_tokens": 100}, response_metadata=None)
    )
    # prompt_chars small, response_chars large: missing-output uses response_chars.
    u = record_call_usage(
        None, prompt_chars=4, response_chars=400, provider_usage=pu, measured_seconds=1.0
    )
    # known 100 + estimate(400)=100 -> 200 (char_estimator ceil(chars/4)).
    assert u["tokens"] == 100 + 100
