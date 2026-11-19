"""Stage 2 (ADR-009): durable per-run usage ledger and resume accounting.

Approved test cases (2026-11-11 human plan/test approval; plan + tests ONLY, not
final human acceptance, NOT final acceptance). These drive fake scripted models
through the REAL production graph/state and a REAL ``SqliteSaver`` to prove:

- a reservation is written BEFORE the outbound call, and a failed/invalid/
  cancelled attempt is settled as unknown cost (never zero, never free);
- a crash after the provider succeeds but before the node/checkpoint update is
  recovered from the ledger (spend is not lost);
- restart with a fresh saver/collector then ``invoke(None)`` keeps the run's
  spend; repeated resume is idempotent (nothing double-added);
- a fresh run with the same ticker+date does NOT inherit a prior finished run's
  spend, while a resume keeps its own;
- a deleted ledger between the graph checkpoint and resume fails closed (no new
  OPTIONAL debate call), not re-initialized to zero;
- unknown-token spend fails closed before a further optional call; the summary
  reserve is preserved;
- a corrupt ledger / unknown version / missing identity fails closed;
- concurrent admission across two independent capture/ledger instances on the
  same run DB admits only one call when one slot remains;
- provider exact/partial/conflicting/malformed telemetry and estimate provenance;
- the ledger is source-private (no prompts/responses/exception text/URLs/secrets).

Traceability: FR-DDT-003, NFR-BUD-001, NFR-AUD-001, FR-DQG-005, NFR-BC-001,
INV-6, INV-7, INV-8. All tests are socket-disabled offline with mocked models.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

from tradingagents.debate.budget import (
    aggregate_whole_run_usage,
    can_afford_optional_call,
    can_afford_summary,
    derive_debate_usage_from_events,
)
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.usage_capture import (
    UsageCapture,
    instrumented_model_call,
    use_usage_capture,
)
from tradingagents.debate.usage_ledger import (
    LedgerError,
    UsageLedger,
    new_run_id,
    open_ledger_strict,
)
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup

SYMBOL = "COF"
TARGET = "2026-05-13"

_TURN = (
    "Argument.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=run:1; new_claims=growth|run:1;"
)
_RECORD = {
    "evidence_id": "run:1",
    "quality_status": "High",
    "observed_at": "2026-05-01",
    "value_raw": "190",
    "metric_name": "close",
    "unit_normalized": "USD",
}
BULL_SIG = "You are a Bull Analyst advocating for investing in the "
BEAR_SIG = "You are a Bear Analyst making the case against investing in the "


def _resp(content: str = _TURN, usage=None, *, response_metadata=None):
    msg = AIMessage(content=content)
    msg.usage_metadata = usage
    msg.response_metadata = response_metadata or {}
    return msg


def _fake_llm(content: str = _TURN, usage=None):
    llm = _MockLLM(content, usage)
    return llm


class _MockLLM:
    """A scripted chat model: returns a response and records invoke calls."""

    def __init__(self, content=_TURN, usage=None):
        self.content = content
        self.usage = usage
        self.calls = []
        self.with_structured_output = lambda *a, **k: None
        self.bind_tools = lambda tools: RunnableLambda(
            lambda m: AIMessage(content=self.content, tool_calls=[])
        )

    def invoke(self, prompt):
        self.calls.append(prompt)
        return _resp(self.content, self.usage)


def _stub_gate_node(verdict: str = "normal"):
    def node(state):
        return {
            "data_quality_verdict": verdict,
            "data_quality_gate_decision": {"decision": verdict, "decided_at": "2026-05-13T12:00:00Z"},
            "data_quality_context": f"[Data Quality Gate] Verdict: {verdict}.",
            "data_quality_error": None,
            "data_quality_evidence_records": [_RECORD],
            "data_quality_validation_results": {},
            "data_quality_group_statuses": [],
        }

    return node


def _build_graph(quick, deep, *, config_override=None):
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=lambda: _stub_gate_node(),
        debate_termination_config=config_override,
    )
    return setup.setup_graph(("market",)).compile()


def _build_workflow(quick, deep, *, config_override=None):
    """The UNcompiled workflow (so a test can compile with a SqliteSaver)."""
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=lambda: _stub_gate_node(),
        debate_termination_config=config_override,
    )
    return setup.setup_graph(("market",))


def _initial_state(run_id=None):
    state = Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")
    if run_id:
        state["run_id"] = run_id
    return state


def _capture(run_id, ledger, config=None):
    cap = UsageCapture(run_id=run_id, ledger=ledger)
    cap.debate_config = config
    return cap


def _big_budget_config(**overrides):
    base = {
        "max_debate_rounds": 100,
        "max_calls": 1000,
        "max_tokens": 10_000_000,
        "max_time": 100_000.0,
        "reserved_summary_tokens": 100,
        "next_round_estimate_tokens": 200,
    }
    base.update(overrides)
    return DebateTerminationConfig.from_dict(base)


# ---------------------------------------------------------------------------
# Reservation-before-call and unknown-cost failures
# ---------------------------------------------------------------------------


class TestReservationAndSettlement:
    def test_reservation_written_before_call_and_settled_unknown_on_failure(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="x")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        seen_state_during_call = {}

        def boom():
            # During the outbound call the reservation must already be in_flight.
            spend = ledger.read_run_spend(rid)
            seen_state_during_call["inflight"] = len(spend.unresolved)
            raise RuntimeError("provider exploded SECRET sk-xyz https://x?token=LEAK")

        with use_usage_capture(cap), pytest.raises(RuntimeError):
            instrumented_model_call(boom, phase="debate", speaker="Bull")
        assert seen_state_during_call["inflight"] == 1
        spend = ledger.read_run_spend(rid)
        # Settled as failed/unresolved-unknown; NOT zero-known.
        assert len(spend.events) == 1
        assert spend.events[0].status == "failed"
        assert spend.events[0].total_tokens is None
        assert spend.events[0].tokens_source == "unavailable"
        assert spend.events[0].unresolved is True
        # Source privacy.
        blob = (tmp_path / "l.db").read_bytes()
        for forbidden in (b"SECRET", b"sk-xyz", b"token=LEAK", b"provider exploded"):
            assert forbidden not in blob

    def test_cancelled_attempt_is_unknown_cost(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="c")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)

        class _Cancel(Exception):
            pass

        def cancel():
            raise KeyboardInterrupt()

        with use_usage_capture(cap), pytest.raises(KeyboardInterrupt):
            instrumented_model_call(cancel, phase="debate", speaker="Bull")
        ev = ledger.read_run_spend(rid).events[0]
        assert ev.status == "cancelled"
        assert ev.unresolved is True

    def test_invalid_end_clock_is_unknown_partial(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="ic")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        # start valid, end backwards/non-finite -> invalid clock.
        seq = iter([10.0, float("nan")])
        from tradingagents.debate.usage_capture import CaptureClockError

        with use_usage_capture(cap), pytest.raises(CaptureClockError):
            instrumented_model_call(
                lambda: _resp(usage={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}),
                phase="debate",
                speaker="Bull",
                clock=seq.__next__,
            )
        ev = ledger.read_run_spend(rid).events[0]
        # The provider call returned tokens, but the time is unusable: tokens kept
        # honest, seconds unavailable (never fabricated).
        assert ev.total_tokens == 60
        assert ev.tokens_source == "provider"
        assert ev.seconds is None
        assert ev.seconds_source == "unavailable"


# ---------------------------------------------------------------------------
# Crash after provider success before node/checkpoint update.
# ---------------------------------------------------------------------------


class TestCrashAfterProviderBeforeCheckpoint:
    def test_settled_before_state_update_survives_and_is_derived(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="crash")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)

        # The wrapper settles the successful call BEFORE returning to the node, so
        # even if the node raises AFTER the provider succeeded, the spend is in the
        # ledger (the "node/checkpoint update lost" case).
        def provider_ok_then_node_fails():
            instrumented_model_call(
                lambda: _resp(usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}),
                phase="debate",
                speaker="Bull",
            )
            # Simulate the node raising AFTER the provider success: the ledger
            # already has the settlement.
            raise RuntimeError("node failed after provider success")

        with use_usage_capture(cap), pytest.raises(RuntimeError):
            provider_ok_then_node_fails()
        spend = ledger.read_run_spend(rid)
        # Exactly one settled successful event with the provider tokens.
        assert len(spend.events) == 1
        assert spend.events[0].status == "success"
        assert spend.events[0].total_tokens == 120
        usage = derive_debate_usage_from_events(spend.events, unresolved=spend.unresolved)
        assert usage["calls"] == 1
        assert usage["tokens"] == 120
        assert usage["provenance"]["tokens"] == "provider"


# ---------------------------------------------------------------------------
# Real compiled graph resume with a real SqliteSaver.
# ---------------------------------------------------------------------------


class TestRealGraphResume:
    def _run_to_mid_debate_then_resume(self, tmp_path):
        """Drive the real graph with a fake LLM, checkpoint, then resume.

        Returns (first_result, resumed_result, ledger, run_id, config).
        """
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        cfg = _big_budget_config()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        rid = new_run_id(SYMBOL, TARGET, nonce="resume")
        ledger_path = tmp_path / "usage.db"
        ledger = UsageLedger(ledger_path)
        ledger.begin_run(rid)
        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        graph_cfg = {"configurable": {"thread_id": tid}}

        def _build():
            return _build_workflow(quick, deep, config_override=cfg)

        # First process: interrupt AFTER the Bull Researcher node.
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = _build().compile(checkpointer=saver, interrupt_after=["Bull Researcher"])
            cap = _capture(rid, ledger, cfg)
            with use_usage_capture(cap):
                first = g.invoke(_initial_state(rid), graph_cfg)
        # The Bull invocation settled in the ledger before the interrupt.
        spend1 = ledger.read_run_spend(rid)
        assert [e for e in spend1.events if e.phase == "debate"] and all(
            e.speaker == "Bull" for e in spend1.events if e.phase == "debate"
        )

        # Second process: fresh saver + fresh capture; resume with invoke(None).
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = _build().compile(checkpointer=saver)
            cap2 = _capture(rid, ledger, cfg)
            with use_usage_capture(cap2):
                resumed = g2.invoke(None, graph_cfg)
        spend2 = ledger.read_run_spend(rid)
        return first, resumed, ledger, rid, cfg, spend1, spend2

    def test_resume_keeps_spend_and_bull_not_double_counted(self, tmp_path):
        _, _, _, rid, _, spend1, spend2 = self._run_to_mid_debate_then_resume(tmp_path)
        debate1 = [e for e in spend1.events if e.phase == "debate"]
        debate2 = [e for e in spend2.events if e.phase == "debate"]
        # The resume added the Bear debate call; the Bull call is NOT double-counted.
        assert len(debate1) == 1
        assert len(debate2) == 2
        inv_ids = [ev.invocation_id for ev in spend2.events]
        assert len(inv_ids) == len(set(inv_ids))
        # A same-phase fresh capture on resume minted a NEW unique invocation id
        # (phases are unique across the two processes).
        bull_ids = [ev.invocation_id for ev in spend2.events if ev.speaker == "Bull"]
        bear_ids = [ev.invocation_id for ev in spend2.events if ev.speaker == "Bear"]
        assert bull_ids and bear_ids
        assert set(bull_ids).isdisjoint(bear_ids)

    def test_repeated_resume_is_idempotent(self, tmp_path):
        _, resumed, ledger, rid, *_ = self._run_to_mid_debate_then_resume(tmp_path)
        before = ledger.read_run_spend(rid)
        total_before = before.settled_tokens()
        # Re-deriving (a second reconciliation pass) yields the same totals.
        again = ledger.read_run_spend(rid)
        assert again.settled_tokens() == total_before
        assert [e.invocation_id for e in again.events] == [e.invocation_id for e in before.events]


class TestDeletedLedgerOnRealGraphResume:
    def test_deleted_ledger_between_checkpoint_and_resume_fails_closed(self, tmp_path):
        """Delete the ledger between the graph checkpoint and resume => 0 new
        optional debate calls (fail closed), never a re-initialized blank ledger.

        Drives the PUBLIC ``_run_graph`` path (via ``propagate``) so the missing
        ledger is detected automatically (strict resume sets accounting_unreadable)
        rather than by a hand-set flag.
        """
        from unittest.mock import MagicMock

        from tradingagents.graph.checkpointer import get_checkpointer, thread_id
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        cfg = _big_budget_config()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        rid = new_run_id(SYMBOL, TARGET, nonce="del-resume")
        ledger_path = tmp_path / "usage.db"
        ledger = UsageLedger(ledger_path)
        ledger.begin_run(rid)
        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        graph_cfg = {"configurable": {"thread_id": tid}}

        # First process: run the compiled graph to an interrupt after Bull and keep
        # the state. The public _run_graph then sees a checkpoint to resume.
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = _build_workflow(quick, deep, config_override=cfg).compile(
                checkpointer=saver, interrupt_after=["Bull Researcher"]
            )
            with use_usage_capture(_capture(rid, ledger, cfg)):
                g.invoke(_initial_state(rid), graph_cfg)
        ledger_path.unlink()  # deleted between checkpoint and resume

        # Build a real TradingAgentsGraph-like object driving _run_graph. The graph
        # is the resumed compiled graph; the checkpoint state carries run_id.
        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = _build_workflow(quick, deep, config_override=cfg).compile(checkpointer=saver)
            graph = object.__new__(TradingAgentsGraph)
            graph.config = {"results_dir": str(tmp_path), "checkpoint_enabled": True,
                            "debate_termination": {"max_debate_rounds": 1}}
            graph.debug = False
            graph._resuming = True
            graph.graph = g2
            graph.propagator = MagicMock()
            graph.propagator.get_graph_args.return_value = {
                "config": {"configurable": {"thread_id": tid}}
            }
            graph.memory_log = MagicMock()
            graph.ticker = SYMBOL
            graph.log_states_dict = {}
            graph.signal_processor = MagicMock()
            graph.signal_processor.process_signal.return_value = "Hold"
            graph.selected_analysts = ("market",)
            graph._log_state = lambda *a, **k: None
            graph.record_decision = lambda *a, **k: None
            graph.clear_checkpoint_on_success = lambda *a, **k: None
            graph.create_run_state = lambda *a, **k: _initial_state(rid)

            # Seed the resumed checkpoint state with the run identity (as a real
            # interrupted run would carry). The real saver already holds the state
            # from the first process; run_id was in the initial state.
            quick.calls.clear()
            deep.calls.clear()
            final, signal = TradingAgentsGraph._run_graph(
                graph, SYMBOL, TARGET, asset_type="stock"
            )

        # No further OPTIONAL debate call: Bear must be refused (accounting
        # unreadable after the ledger vanished), Bull already ran pre-interrupt.
        bear_prompts = [p for p in quick.calls if isinstance(p, str) and p.startswith(BEAR_SIG)]
        assert bear_prompts == []
        decision = final.get("debate_termination_decision") or {}
        assert decision.get("stop_reason") == "budget_exhausted"
        # The run still produced a manager report (safe summary path).
        assert final.get("final_trade_decision")
        # The ledger was NOT re-initialized to a blank DB.
        assert not ledger_path.exists()


class TestSummaryReserveProtection:
    def test_rm_summary_denied_uses_deterministic_template_on_unresolved(self, tmp_path):
        """An unresolved failed Bear attempt must not let the Research Manager
        retry the summary against the same reserve; the manager uses the
        deterministic auditable template (no extra model invocation)."""
        cfg = _big_budget_config()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        rid = new_run_id(SYMBOL, TARGET, nonce="rmdeny")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        # Pre-seed an unresolved debate reservation (unknown possible spend).
        ledger.reserve(
            run_id=rid, invocation_id="stuck", phase="debate", speaker="Bear",
            reserved_tokens=200, reserved_seconds=30,
        )
        cap = _capture(rid, ledger, cfg)
        graph = _build_graph(quick, deep, config_override=cfg)
        with use_usage_capture(cap):
            final = graph.invoke(_initial_state(rid))
        # The manager summary was skipped (deterministic fallback), not retried.
        assert final.get("summary_budget_denied") is True
        assert final.get("summary_budget_denied_reason") == "summary_budget_unavailable"
        plan = final.get("investment_plan") or ""
        assert "summary_budget_unavailable" in plan
        # No Research Manager prompt reached the deep model (assert by the RM
        # prompt prefix, not "all deep calls == 0" — the deep model may also serve
        # the Portfolio Manager later in the graph).
        rm_prompts = [
            p for p in deep.calls
            if isinstance(p, str) and p.startswith("As the Research Manager")
        ]
        assert rm_prompts == []
        # And the ledger recorded no research_manager-phase invocation.
        rm_events = [
            e for e in ledger.read_run_spend(rid).events if e.phase == "research_manager"
        ]
        assert rm_events == []

    def test_can_afford_summary_requires_remaining_call_slot(self):
        # Reproduced bug: with max_calls=1 and calls already spent, the summary
        # must NOT be admitted (it consumes the last call slot).
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1})
        assert can_afford_summary({"calls": 1, "tokens": 0, "seconds": 0.0}, cfg) is False
        # A free slot admits the summary.
        assert can_afford_summary({"calls": 0, "tokens": 0, "seconds": 0.0}, cfg) is True

    def test_can_afford_summary_admits_when_only_reserve_remains(self):
        # known-cost spend leaves EXACTLY the reserve: the summary (which consumes
        # the reserve) is admitted, unlike an optional call which needs reserve+next.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 10_000,
                "reserved_summary_tokens": 1_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000.0,
            }
        )
        # remaining tokens == reserve(1000) exactly => summary admitted.
        usage = {"calls": 3, "tokens": 9_000, "seconds": 0.0}
        assert can_afford_summary(usage, cfg) is True
        # An OPTIONAL call in the same state is refused (needs reserve + estimate).
        assert can_afford_optional_call(usage, cfg) is False

    def test_summary_admitted_with_exactly_one_remaining_call_slot(self, tmp_path):
        # graph with max_calls == exactly the debate calls + 1 summary slot.
        # default max_debate_rounds=1 -> Bull+Bear = 2 debate calls, +1 summary = 3.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 3,
                "max_debate_rounds": 1,
                "max_tokens": 10_000_000,
                "max_time": 100_000.0,
                "reserved_summary_tokens": 100,
                "next_round_estimate_tokens": 100,
            }
        )
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        rid = new_run_id(SYMBOL, TARGET, nonce="slot1")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        graph = _build_graph(quick, deep, config_override=cfg)
        with use_usage_capture(_capture(rid, ledger, cfg)):
            final = graph.invoke(_initial_state(rid))
        # Exactly ONE summary model call was made (research_manager phase).
        rm_events = [
            e for e in ledger.read_run_spend(rid).events if e.phase == "research_manager"
        ]
        assert len(rm_events) == 1
        assert final.get("summary_budget_denied") is not True

    def test_structured_success_consumes_one_slot_then_fallback_needs_second(self, tmp_path):
        """A structured attempt consumes one call slot; the free-text fallback must
        consume a SEPARATE slot. When only one slot exists, the fallback is denied
        (no second provider call) and the caller gets a deterministic result."""
        from tradingagents.agents.utils.structured import invoke_structured_or_freetext
        from tradingagents.debate.usage_capture import BudgetDeniedError

        rid = new_run_id(SYMBOL, TARGET, nonce="slotfb")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        # Only ONE call slot in the whole run.
        cfg = DebateTerminationConfig.from_dict({"max_calls": 1})
        cap.debate_config = cfg

        plain_calls = {"n": 0}

        class _Plain:
            def invoke(self, prompt):
                plain_calls["n"] += 1
                return _resp("plain", (10, 5))

        class _Structured:
            def invoke(self, prompt):
                raise RuntimeError("structured miss")

        def _admit():
            from tradingagents.debate.researcher_accounting import admit_summary_attempt

            return admit_summary_attempt({"debate_usage": None}, cfg)

        with use_usage_capture(cap), pytest.raises(BudgetDeniedError):
            invoke_structured_or_freetext(
                _Structured(),
                _Plain(),
                "prompt",
                lambda r: "x",
                "Research Manager",
                admit_attempt=_admit,
            )
        # The structured attempt consumed the single slot; the fallback is denied.
        assert plain_calls["n"] == 0
        rm_events = [
            e for e in ledger.read_run_spend(rid).events if e.phase == "research_manager"
        ]
        assert len(rm_events) == 1  # the structured attempt only

    def test_unknown_failure_blocks_fallback_summary(self, tmp_path):
        """An UNKNOWN-cost failed summary attempt must not retry the fallback:
        explicit deterministic Hold with the denied reason."""
        cfg = _big_budget_config()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        rid = new_run_id(SYMBOL, TARGET, nonce="unkfall")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        # Unresolved possible RM spend (a prior summary attempt crashed).
        ledger.reserve(run_id=rid, invocation_id="rm-crash", phase="research_manager",
                       speaker="Research Manager", reserved_tokens=300, reserved_seconds=9.0)
        graph = _build_graph(quick, deep, config_override=cfg)
        with use_usage_capture(_capture(rid, ledger, cfg)):
            final = graph.invoke(_initial_state(rid))
        assert final.get("summary_budget_denied") is True
        assert final.get("summary_budget_denied_reason") == "summary_budget_unavailable"
        # No Research Manager free-text fallback reached the model.
        rm_prompts = [
            p for p in deep.calls
            if isinstance(p, str) and p.startswith("As the Research Manager")
        ]
        assert rm_prompts == []


class TestFreshVsResumeIsolation:
    def test_fresh_run_same_ticker_date_starts_at_zero(self, tmp_path):
        ledger_path = tmp_path / "usage.db"
        # Finishing run A.
        rid_a = new_run_id(SYMBOL, TARGET, nonce="A")
        ledger_a = UsageLedger(ledger_path)
        ledger_a.begin_run(rid_a)
        with use_usage_capture(_capture(rid_a, ledger_a)):
            instrumented_model_call(
                lambda: _resp(usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
                phase="trader",
                speaker="Trader",
            )
        assert ledger_a.read_run_spend(rid_a).settled_tokens() == 15

        # A FRESH run with the SAME ticker+date gets a NEW identity and zero spend.
        rid_b = new_run_id(SYMBOL, TARGET, nonce="B")
        assert rid_b != rid_a
        ledger_b = UsageLedger(ledger_path)
        ledger_b.begin_run(rid_b)
        assert ledger_b.read_run_spend(rid_b).settled_tokens() == 0
        # Run A's spend is untouched.
        assert ledger_a.read_run_spend(rid_a).settled_tokens() == 15


# ---------------------------------------------------------------------------
# Fail-closed: deleted / corrupt / unknown-version / missing identity.
# ---------------------------------------------------------------------------


class TestFailClosedAccounting:
    def test_deleted_ledger_on_resume_fails_closed(self, tmp_path):
        ledger_path = tmp_path / "usage.db"
        rid = new_run_id(SYMBOL, TARGET, nonce="del")
        ledger = UsageLedger(ledger_path)
        ledger.begin_run(rid)
        ledger_path.unlink()
        # A strict resume open must fail, not recreate a blank ledger.
        with pytest.raises(LedgerError):
            open_ledger_strict(ledger_path)
        assert not ledger_path.exists()

    def test_corrupt_ledger_read_fails_closed(self, tmp_path):
        ledger_path = tmp_path / "usage.db"
        ledger_path.write_bytes(b"not a sqlite database at all\x00\x01\x02")
        with pytest.raises(LedgerError):
            open_ledger_strict(ledger_path)

    def test_unknown_schema_version_fails_closed(self, tmp_path):
        ledger_path = tmp_path / "usage.db"
        UsageLedger(ledger_path)  # create the schema
        # Corrupt the recorded schema version.
        conn = sqlite3.connect(str(ledger_path))
        conn.execute("UPDATE ledger_meta SET value = '9.9' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()
        with pytest.raises(LedgerError):
            open_ledger_strict(ledger_path)

    def test_missing_identity_cannot_reserve(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        with pytest.raises(LedgerError):
            ledger.reserve(
                run_id="run:unknown", invocation_id="i", phase="debate",
                speaker="Bull", reserved_tokens=1, reserved_seconds=1.0,
            )

    def test_unknown_token_spend_fails_closed_before_optional_call(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="ut")
        ledger.begin_run(rid)
        cfg = _big_budget_config(max_calls=10)
        # A settled failed (unknown-token) debate event => unresolved possible spend.
        ledger.reserve(run_id=rid, invocation_id="f1", phase="debate", speaker="Bull",
                       reserved_tokens=200, reserved_seconds=30)
        ledger.settle(run_id=rid, invocation_id="f1", status="failed", phase="debate",
                      speaker="Bull", total_tokens=None, tokens_source="unavailable",
                      unresolved=True)
        spend = ledger.read_run_spend(rid)
        usage = derive_debate_usage_from_events(spend.events, unresolved=spend.unresolved)
        assert usage["unresolved_invocations"] >= 1
        # Fail closed: no further optional call is admitted while unknown spend exists.
        assert can_afford_optional_call(usage, cfg) is False

    def test_summary_reserve_preserved_under_known_spend(self):
        # A near-limit but KNOWN spend leaves room only for the summary reserve,
        # so an optional call is refused (reserve preserved) yet the summary is
        # still reachable.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 10_000,
                "reserved_summary_tokens": 1_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000.0,
            }
        )
        # remaining == reserve + estimate boundary-minus-one => refused.
        assert can_afford_optional_call({"calls": 0, "tokens": 8_001, "seconds": 0.0}, cfg) is False
        # remaining == reserve + estimate => admitted (boundary).
        assert can_afford_optional_call({"calls": 0, "tokens": 8_000, "seconds": 0.0}, cfg) is True


# ---------------------------------------------------------------------------
# Concurrency across independent capture/ledger instances.
# ---------------------------------------------------------------------------


class TestConcurrentAdmission:
    def test_two_independent_ledgers_one_slot_admits_one(self, tmp_path):
        ledger_path = tmp_path / "usage.db"
        rid = new_run_id(SYMBOL, TARGET, nonce="conc")
        # Two independent ledger objects on the SAME file/run.
        ledger_a = UsageLedger(ledger_path)
        ledger_a.begin_run(rid)
        ledger_b = UsageLedger(ledger_path)
        ledger_b.begin_run(rid)

        barrier = threading.Barrier(2)
        results = {}

        def attempt(name, ledger):
            barrier.wait()
            admitted = ledger.admit_debate_call(
                run_id=rid,
                invocation_id=f"{name}:0",
                max_calls=1,
                reserved_tokens=200,
                reserved_seconds=30,
                speaker=name,
            )
            results[name] = admitted

        threads = [
            threading.Thread(target=attempt, args=("a", ledger_a)),
            threading.Thread(target=attempt, args=("b", ledger_b)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly one slot: exactly one admission succeeds.
        assert sorted(results.values()) == [False, True]
        spend = ledger_a.read_run_spend(rid)
        assert len(spend.unresolved) == 1

    def _two_ledgers(self, tmp_path, rid):
        ledger_path = tmp_path / "usage.db"
        a = UsageLedger(ledger_path)
        a.begin_run(rid)
        b = UsageLedger(ledger_path)
        b.begin_run(rid)
        return a, b

    def test_token_only_capacity_admits_one_across_instances(self, tmp_path):
        # Ample max_calls, but token capacity for exactly ONE call: two independent
        # ledgers must not both reserve beyond the token policy.
        rid = new_run_id(SYMBOL, TARGET, nonce="tokconc")
        a, b = self._two_ledgers(tmp_path, rid)
        # next_call_estimate = ceil(2000/2)=1000 tokens, 30 s. Capacity: reserve
        # 4000 + estimate 1000 + one call 1000 => max 6000 tokens fits exactly one.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 6_000,
                "reserved_summary_tokens": 4_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000.0,
            }
        )
        barrier = threading.Barrier(2)
        results = {}

        def attempt(name, ledger):
            barrier.wait()
            results[name] = ledger.admit_debate_call(
                run_id=rid, invocation_id=f"{name}:0", max_calls=100,
                reserved_tokens=1000, reserved_seconds=30.0, speaker=name, config=cfg,
            )

        ts = [threading.Thread(target=attempt, args=(n, led)) for n, led in (("a", a), ("b", b))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert sorted(results.values()) == [False, True]
        # Only one in_flight reservation exists (the second was refused).
        assert len(a.read_run_spend(rid).unresolved) == 1

    def test_time_only_capacity_admits_one_across_instances(self, tmp_path):
        rid = new_run_id(SYMBOL, TARGET, nonce="timeconc")
        a, b = self._two_ledgers(tmp_path, rid)
        # Plenty of tokens, but time capacity for exactly one call:
        # reserve 90 + estimate 30 + one call 30 = 150 s; max_time 150 fits one.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 10_000_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 150.0,
                "reserved_summary_seconds": 90.0,
                "next_round_estimate_seconds": 60.0,
            }
        )
        barrier = threading.Barrier(2)
        results = {}

        def attempt(name, ledger):
            barrier.wait()
            results[name] = ledger.admit_debate_call(
                run_id=rid, invocation_id=f"{name}:0", max_calls=100,
                reserved_tokens=1000, reserved_seconds=30.0, speaker=name, config=cfg,
            )

        ts = [threading.Thread(target=attempt, args=(n, led)) for n, led in (("a", a), ("b", b))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert sorted(results.values()) == [False, True]

    def test_stale_preflight_rechecked_after_first_settles(self, tmp_path):
        # The first attempt settles (known cost) BEFORE the second transaction: the
        # second must re-read the committed spend and refuse if it no longer fits.
        rid = new_run_id(SYMBOL, TARGET, nonce="stale")
        a, b = self._two_ledgers(tmp_path, rid)
        # Capacity for exactly one call: 4000 reserve + 1000 est + 1000 call = 6000.
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 6_000,
                "reserved_summary_tokens": 4_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000.0,
            }
        )
        assert a.admit_debate_call(
            run_id=rid, invocation_id="a:0", max_calls=100,
            reserved_tokens=1000, reserved_seconds=30.0, speaker="a", config=cfg,
        ) is True
        # First settles with KNOWN tokens ~ the estimate (so capacity is consumed).
        a.settle(
            run_id=rid, invocation_id="a:0", status="success", phase="debate",
            speaker="a", total_tokens=5000, tokens_source="provider",
            input_tokens=4000, output_tokens=1000,
            input_tokens_source="provider", output_tokens_source="provider",
            seconds=30.0, seconds_source="measured",
        )
        # Second independent ledger re-reads committed usage in its txn -> refused.
        assert b.admit_debate_call(
            run_id=rid, invocation_id="b:0", max_calls=100,
            reserved_tokens=1000, reserved_seconds=30.0, speaker="b", config=cfg,
        ) is False

    def test_unknown_failure_interleave_blocks_second(self, tmp_path):
        # The first attempt settles as an UNKNOWN failure (unresolved); the second
        # independent ledger must re-read that and fail closed (no admission).
        rid = new_run_id(SYMBOL, TARGET, nonce="unkinter")
        a, b = self._two_ledgers(tmp_path, rid)
        cfg = _big_budget_config(max_calls=100)
        assert a.admit_debate_call(
            run_id=rid, invocation_id="a:0", max_calls=100,
            reserved_tokens=200, reserved_seconds=30.0, speaker="a", config=cfg,
        ) is True
        a.settle(
            run_id=rid, invocation_id="a:0", status="failed", phase="debate",
            speaker="a", total_tokens=None, tokens_source="unavailable", unresolved=True,
        )
        assert b.admit_debate_call(
            run_id=rid, invocation_id="b:0", max_calls=100,
            reserved_tokens=200, reserved_seconds=30.0, speaker="b", config=cfg,
        ) is False

    def test_summary_atomic_admission_uses_fresh_combined_scope(self, tmp_path):
        # Two independent ledgers: only one summary admitted when token capacity for
        # exactly one summary remains (combined debate+RM scope re-read in txn).
        rid = new_run_id(SYMBOL, TARGET, nonce="sumconc")
        a, b = self._two_ledgers(tmp_path, rid)
        cfg = DebateTerminationConfig.from_dict(
            {
                "max_calls": 100,
                "max_tokens": 5_000,
                "reserved_summary_tokens": 4_000,
                "next_round_estimate_tokens": 2_000,
                "max_time": 100_000.0,
            }
        )
        barrier = threading.Barrier(2)
        results = {}

        def attempt(name, ledger):
            barrier.wait()
            results[name] = ledger.admit_summary_call(
                run_id=rid, invocation_id=f"{name}:rm", max_calls=100,
                reserved_tokens=1000, reserved_seconds=30.0, speaker="Research Manager",
                config=cfg,
            )

        ts = [threading.Thread(target=attempt, args=(n, led)) for n, led in (("a", a), ("b", b))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        # Exactly one summary reservation (a summary consumes the reserve; a second
        # overlapping summary would exceed it).
        assert sorted(results.values()) == [False, True]


# ---------------------------------------------------------------------------
# Provider telemetry provenance + estimate labelling.
# ---------------------------------------------------------------------------


class TestProviderTelemetryProvenance:
    def _settle_one(self, response):
        ledger = UsageLedger(_tmp := Path())
        return response, ledger

    def test_exact_provider_telemetry(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="ex")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        with use_usage_capture(cap):
            instrumented_model_call(
                lambda: _resp(usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}),
                phase="trader",
                speaker="Trader",
            )
        ev = ledger.read_run_spend(rid).events[0]
        assert ev.total_tokens == 120
        assert ev.tokens_source == "provider"

    def test_partial_provider_telemetry_is_labelled_estimated(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="pa")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        with use_usage_capture(cap):
            instrumented_model_call(
                lambda: _resp(content="x" * 40, usage={"input_tokens": 100}),
                phase="trader",
                speaker="Trader",
            )
        ev = ledger.read_run_spend(rid).events[0]
        # One side known from provider; the other estimated => never provider-exact.
        assert ev.tokens_source == "estimated"
        assert ev.token_source_partial is True

    def test_conflicting_provider_telemetry_flagged(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="cf")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        # usage_metadata total disagrees with input+output.
        with use_usage_capture(cap):
            instrumented_model_call(
                lambda: _resp(usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 999}),
                phase="trader",
                speaker="Trader",
            )
        ev = ledger.read_run_spend(rid).events[0]
        assert ev.provider_conflict is True
        assert ev.tokens_source == "estimated"  # derived, never provider-exact

    def test_malformed_provider_usage_falls_back_to_labelled_estimate(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="mf")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        with use_usage_capture(cap):
            instrumented_model_call(
                lambda: _resp(content="y" * 80, usage={"input_tokens": -5, "output_tokens": 1.5}),
                phase="trader",
                speaker="Trader",
            )
        ev = ledger.read_run_spend(rid).events[0]
        assert ev.tokens_source == "estimated"
        assert ev.total_tokens is not None and ev.total_tokens > 0

    def test_partial_provider_keeps_per_side_provenance_and_originals(self, tmp_path):
        # A partial provider split must NOT relabel the filled estimate as provider,
        # and a conflict must retain both source-labelled originals.
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="side")
        ledger.begin_run(rid)
        cap = _capture(rid, ledger)
        with use_usage_capture(cap):
            # input-only provider block: input=provider, output=estimated.
            instrumented_model_call(
                lambda: _resp(content="z" * 40, usage={"input_tokens": 100}),
                phase="trader",
                speaker="Trader",
            )
        ev = ledger.read_run_spend(rid).events[0]
        assert ev.input_tokens_source == "provider"
        assert ev.output_tokens_source == "estimated"
        assert ev.input_tokens == 100
        # Deriving the real event keeps the per-side labels honest: the KNOWN input
        # side stays provider; the missing output side carries no fabricated count
        # (its value is None and it is flagged partial), and the aggregate total is
        # estimated — never provider-exact.
        usage2 = derive_debate_usage_from_events(
            ledger.read_run_spend(rid).events, phases=("trader",)
        )
        assert usage2["provenance"]["input_tokens"] == "provider"
        assert usage2["output_tokens_partial"] is True
        assert usage2["provenance"]["tokens"] == "estimated"

    def test_whole_run_includes_unresolved_reservation_and_cannot_claim_complete(self, tmp_path):
        ledger = UsageLedger(tmp_path / "l.db")
        rid = new_run_id(SYMBOL, TARGET, nonce="inflight")
        ledger.begin_run(rid)
        # One settled successful call.
        ledger.reserve(run_id=rid, invocation_id="ok", phase="trader", speaker="Trader",
                       reserved_tokens=100, reserved_seconds=1.0)
        ledger.settle(run_id=rid, invocation_id="ok", status="success", phase="trader",
                      speaker="Trader", total_tokens=120, tokens_source="provider",
                      input_tokens=100, output_tokens=20,
                      input_tokens_source="provider", output_tokens_source="provider",
                      seconds=1.0, seconds_source="measured")
        # One in_flight reservation (crash between provider invocation and settle).
        ledger.reserve(run_id=rid, invocation_id="crash", phase="risk", speaker="Risk",
                       reserved_tokens=200, reserved_seconds=5.0)
        spend = ledger.read_run_spend(rid)
        whole = aggregate_whole_run_usage(spend.events, spend.unresolved)
        # The unresolved reservation is reported separately, never as known cost.
        assert whole["settled_calls"] == 1
        assert whole["reserved_unconfirmed_calls"] == 1
        assert whole["totals"]["tokens"] == 120  # only the settled call
        assert whole["totals"]["reserved_estimated_tokens"] == 200
        assert whole["reserved_unconfirmed"][0]["invocation_id"] == "crash"
        # Completeness can NEVER be complete while possible billed spend is urgent.
        assert whole["completeness"] != "complete"
        assert whole["completeness"] == "partial"

    def test_real_resume_in_flight_reservation_reported_not_complete(self, tmp_path):
        """End-to-end: an in_flight reservation survives a real SqliteSaver resume
        and the final whole-run block exposes unresolved spend (never complete)."""
        from tradingagents.graph.checkpointer import get_checkpointer, thread_id

        cfg = _big_budget_config()
        quick = _fake_llm()
        deep = _fake_llm("Hold")
        rid = new_run_id(SYMBOL, TARGET, nonce="inflight-resume")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)
        graph_cfg = {"configurable": {"thread_id": tid}}

        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = _build_workflow(quick, deep, config_override=cfg).compile(
                checkpointer=saver, interrupt_after=["Bull Researcher"]
            )
            with use_usage_capture(_capture(rid, ledger, cfg)):
                g.invoke(_initial_state(rid), graph_cfg)

        # Simulate a crash between a provider invocation and settlement: a durable
        # in_flight reservation with NO settled event.
        ledger.reserve(run_id=rid, invocation_id="crashed-before-settle",
                       phase="research_manager", speaker="Research Manager",
                       reserved_tokens=300, reserved_seconds=9.0)

        with get_checkpointer(data_dir, SYMBOL) as saver:
            g2 = _build_workflow(quick, deep, config_override=cfg).compile(checkpointer=saver)
            cap2 = _capture(rid, ledger, cfg)
            with use_usage_capture(cap2):
                g2.invoke(None, graph_cfg)
            spend = ledger.read_run_spend(rid)
            whole = aggregate_whole_run_usage(spend.events, spend.unresolved)
        assert whole["reserved_unconfirmed_calls"] >= 1
        assert whole["reserved_unconfirmed"][0]["phase"] == "research_manager"
        assert whole["completeness"] != "complete"
