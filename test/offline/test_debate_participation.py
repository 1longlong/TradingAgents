"""Offline tests for deterministic participation truth and the sanitized
failure audit (added by the DEBT-021/033 repair).

These pin the authoritative participation derivation (structured turns win; a
legacy prose-only history does NOT prove execution), the top-level termination
decision merge (including a refused speaker nested in the trace), and the
allow-listed-only failure audit that never stores raw exception text.

Traceability: NFR-AUD-001 (auditability), INV-6 (auditability); supports
INV-1 (fail closed) for the sanitized failure channel.
"""

from __future__ import annotations

import json

from tradingagents.debate.failure_audit import (
    ERROR_CLASS_PROVIDER,
    ERROR_CLASS_UNKNOWN,
    REASON_UNKNOWN,
    build_failure_record,
    classify_error,
    iter_failure_records,
    record_failure,
    resolve_audit_paths,
)
from tradingagents.debate.participation import (
    STATUS_BOTH,
    STATUS_NONE,
    STATUS_ONE,
    STATUS_UNKNOWN,
    participation_prompt_block,
    summarize_participation,
)


def _state(turns=None, bull="", bear="", history=""):
    return {
        "bull_history": bull,
        "bear_history": bear,
        "history": history,
        "current_response": "",
        "count": 0,
        "turns": turns if turns is not None else [],
    }


class TestParticipation:
    def test_both_executed_via_structured_turns(self):
        p = summarize_participation(
            _state(
                turns=[{"speaker": "Bull", "content": "b"}, {"speaker": "Bear", "content": "x"}],
                bull="b",
                bear="x",
            )
        )
        assert p["status"] == STATUS_BOTH
        assert p["executed_speakers"] == ["Bull", "Bear"]
        assert p["evidence"] == "structured"

    def test_one_executed_other_refused(self):
        decision = {
            "stop_reason": "budget_exhausted",
            "refused_speaker": "Bear",
        }
        p = summarize_participation(
            _state(turns=[{"speaker": "Bull", "content": "b"}], bull="b"),
            debate_termination_decision=decision,
        )
        assert p["status"] == STATUS_ONE
        assert p["executed_speakers"] == ["Bull"]
        assert p["bear"] == "not_executed"
        assert "Bear" in p["skipped_speakers"]

    def test_refused_speaker_nested_in_trace_actual(self):
        decision = {
            "stop_reason": "budget_exhausted",
            "trace": [{"rule": "budget_precall", "actual": {"refused_speaker": "Bear"}}],
        }
        p = summarize_participation(
            _state(turns=[{"speaker": "Bull", "content": "b"}], bull="b"),
            debate_termination_decision=decision,
        )
        assert p["bear"] == "not_executed"

    def test_legacy_prose_alone_is_unverified_not_executed(self):
        # No structured turns, but histories are non-empty -> unverified.
        p = summarize_participation(_state(bull="bull prose", bear="bear prose"))
        assert p["status"] == STATUS_UNKNOWN
        assert p["evidence"] == "legacy"
        assert p["bull"] == "unverified"
        assert p["bear"] == "unverified"

    def test_no_turns_no_history_is_none(self):
        p = summarize_participation(_state())
        assert p["status"] == STATUS_NONE
        assert p["evidence"] == "absent"

    def test_malformed_structured_turns_stay_unverified(self):
        p = summarize_participation(_state(turns=[{"speaker": "Chairman", "content": "x"}]))
        assert p["status"] == STATUS_UNKNOWN
        assert p["evidence"] == "conflicting"

    def test_unhashable_list_speaker_fails_closed_unverified(self):
        # A list-valued speaker is unhashable; must not raise, and must fail
        # closed to unverified (never inferred as executed).
        p = summarize_participation(_state(turns=[{"speaker": [], "content": "x"}]))
        assert p["status"] == STATUS_UNKNOWN
        assert p["evidence"] == "conflicting"
        assert p["bull"] == "unverified" and p["bear"] == "unverified"

    def test_non_mapping_turn_fails_closed_unverified(self):
        # A non-mapping entry in the structured turns list is malformed.
        p = summarize_participation(_state(turns=["not-a-mapping"]))
        assert p["status"] == STATUS_UNKNOWN
        assert p["evidence"] == "conflicting"

    def test_list_valued_speaker_never_counts_as_executed(self):
        # A list-valued speaker is never counted as Bull/Bear; the whole
        # structured state is untrusted -> unverified (the valid Bull turn is
        # counted for `bull_turns` but execution is NOT promoted to executed).
        p = summarize_participation(
            _state(turns=[{"speaker": [], "content": "x"}, {"speaker": "Bull", "content": "b"}])
        )
        assert p["bull_turns"] == 1  # only the valid Bull turn counts
        assert p["status"] == STATUS_UNKNOWN
        assert p["evidence"] == "conflicting"

    def test_structured_turns_conflicting_with_prose(self):
        # Structured turn only for Bull, but bear prose exists -> conflict.
        p = summarize_participation(
            _state(turns=[{"speaker": "Bull", "content": "b"}], bull="b", bear="phantom bear")
        )
        assert p["bear"] == "unverified"
        assert p["evidence"] == "conflicting"

    def test_blocked_zero_turns_explicit_data_quality_blocked(self):
        p = summarize_participation(_state(), gate_verdict="blocked")
        assert p["status"] == STATUS_NONE
        assert p["skip_reason"] == "data_quality_blocked"
        assert p["blocked"] is True

    def test_prompt_block_never_says_no_speaker_for_unverified(self):
        p = summarize_participation(_state(bull="prose", bear="prose"))
        block = participation_prompt_block(p)
        assert "unverified" in block.lower()
        assert "No speaker executed a model call" not in block


class TestFailureAudit:
    def test_classify_error_uses_type_name_only(self):
        assert classify_error(TimeoutError("SECRET token sk-abc")) == "invocation_timeout"
        assert classify_error(ConnectionError("x")) == ERROR_CLASS_PROVIDER
        assert classify_error(ValueError("SECRET")) == ERROR_CLASS_UNKNOWN

    def test_record_has_no_raw_text(self):
        secret = "Bearer sk-SECRET-123 prompt body"
        rec = build_failure_record(
            run_id="2026-11-05/NVDA",
            turn="Bull",
            speaker="Bull",
            phase="debate_invocation",
            error=RuntimeError(secret),
            usage_snapshot={"calls": 1, "failed_calls": 1, "transport_attempts": None},
        )
        blob = json.dumps(rec)
        assert "SECRET" not in blob
        assert "sk-" not in blob
        assert "prompt body" not in blob
        assert rec["error_class"] in {
            "invocation_aborted",
            "invocation_timeout",
            "provider_error",
            "unknown_error",
        }
        # transport_attempts None is dropped; only numeric safe usage kept.
        assert rec["safe_usage"] == {"calls": 1, "failed_calls": 1}

    def test_reason_is_allowlisted(self):
        rec = build_failure_record(
            run_id="r", turn="Bull", speaker="Bull", phase="p",
            error=None, error_class=ERROR_CLASS_UNKNOWN, reason="sk-secret-value",
        )
        assert rec["reason"] == REASON_UNKNOWN

    def test_append_and_iterate(self, tmp_path):
        path = tmp_path / "audit" / "failure.jsonl"
        record_failure(
            path, run_id="r", turn="Bear", speaker="Bear", phase="p",
            error=TimeoutError("x"), reason="clock_invalid",
        )
        records = list(iter_failure_records(path))
        assert len(records) == 1
        assert records[0]["speaker"] == "Bear"
        assert records[0]["reason"] == "clock_invalid"

    def test_noop_without_path(self):
        assert record_failure(None, run_id="r", turn="B", speaker="B", phase="p", error=None) is not None

    def test_resolve_default_paths_under_results_dir(self):
        failure, quarantine = resolve_audit_paths(
            {"results_dir": "/tmp/ta", "company_of_interest": "NVDA", "trade_date": "2026-11-05"}
        )
        assert failure and "nvda" in failure and failure.endswith(".jsonl")
        assert quarantine and quarantine.endswith(".jsonl")
        assert "/../" not in failure

    def test_resolve_no_results_dir_is_none(self):
        assert resolve_audit_paths({}) == (None, None)
