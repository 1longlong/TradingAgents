"""Stage 2 (ADR-009): truthful whole-run usage aggregation.

Approved test cases (2026-11-11 human plan/test approval; plan + tests ONLY, not
final human acceptance). These drive an end-to-end mocked FULL graph and assert
EXACT whole-run totals across every model-calling phase:

- analysts (market) + the structured-output failure → free-text fallback +
  the Bull/Bear debate + the Research Manager + the Trader + the three risk
  analysts + the Portfolio Manager;
- the debate call is counted ONCE (through the ledger), never both through a
  node tracker and a second aggregate;
- provider exact telemetry is ``complete``; a failed/unknown-cost call is
  ``partial``; zero accounted calls is ``unknown``;
- the report artifacts (``run_summary.json`` + markdown) and the same structure
  agree on the totals and the execution identity;
- a structured attempt that falls back is TWO counted attempts (structured miss
  + free-text retry), and a structured result without ``.content`` is not
  estimated as 0 output.

Traceability: FR-DQG-005, NFR-AUD-001, NFR-BUD-001, FR-DDT-003, NFR-BC-001,
INV-6, INV-8. All tests are socket-disabled offline with mocked models.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

from tradingagents.agents.utils.structured import invoke_structured_or_freetext
from tradingagents.debate.budget import (
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    COMPLETENESS_UNKNOWN,
    aggregate_whole_run_usage,
)
from tradingagents.debate.config import DebateTerminationConfig
from tradingagents.debate.usage_capture import UsageCapture, use_usage_capture
from tradingagents.debate.usage_ledger import UsageLedger, new_run_id
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup
from tradingagents.report_artifacts import write_report_artifacts

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


def _resp(content: str, tokens: tuple[int, int]):
    inp, out = tokens
    msg = AIMessage(content=content)
    msg.usage_metadata = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    msg.response_metadata = {}
    return msg


class _ScriptedLLM:
    """Every text invocation returns fixed provider usage (exact telemetry).

    ``invoke_calls`` is the INDEPENDENT raw model-invocation counter: it counts
    both direct ``invoke`` calls AND invocations through a ``bind_tools`` chain,
    so a test can compare the ledger total to what the model layer actually saw
    (proving no model call is missing from the ledger).
    """

    def __init__(self, content: str, tokens: tuple[int, int] = (100, 20)):
        self.content = content
        self.tokens = tokens
        self.invoke_calls = 0
        self.bind_invoke_calls = 0

    @property
    def total_model_calls(self) -> int:
        return self.invoke_calls + self.bind_invoke_calls

    def with_structured_output(self, *a, **k):
        return None  # force the free-text path (simplest deterministic count)

    def bind_tools(self, tools):
        def _chain(m):
            self.bind_invoke_calls += 1
            return _resp(self.content, self.tokens)

        return RunnableLambda(_chain)

    def invoke(self, prompt):
        self.invoke_calls += 1
        return _resp(self.content, self.tokens)


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


def _build_full_graph(quick, deep, *, config_override=None):
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


def _initial_state(run_id):
    from tradingagents.graph.propagation import Propagator

    state = Propagator().create_initial_state(SYMBOL, TARGET, asset_type="stock")
    state["run_id"] = run_id
    return state


def _run_full(tmp_path, *, quick_content=_TURN, deep_content="Hold", tokens=(100, 20), cfg=None):
    from tradingagents.debate.budget import aggregate_whole_run_usage as agg

    rid = new_run_id(SYMBOL, TARGET, nonce="full")
    ledger = UsageLedger(tmp_path / "usage.db")
    ledger.begin_run(rid)
    quick = _ScriptedLLM(quick_content, tokens)
    deep = _ScriptedLLM(deep_content, tokens)
    cap = UsageCapture(run_id=rid, ledger=ledger)
    cap.debate_config = cfg or DebateTerminationConfig.from_dict({"max_debate_rounds": 1})
    graph = _build_full_graph(quick, deep, config_override=cfg)
    with use_usage_capture(cap):
        final = graph.invoke(_initial_state(rid))
    whole = agg(ledger.read_run_spend(rid).events)
    return final, whole, ledger, rid, quick, deep


class TestWholeRunEndToEnd:
    def test_exact_whole_run_totals_cover_all_phases(self, tmp_path):
        final, whole, ledger, rid, quick, deep = _run_full(tmp_path)
        by_phase = whole["by_phase"]
        # Every model-calling phase is represented.
        for phase in ("analyst", "debate", "research_manager", "trader", "risk", "portfolio"):
            assert phase in by_phase, phase
        # One round of debate (default max_debate_rounds=1): Bull + Bear.
        assert by_phase["debate"]["calls"] == 2
        # One market analyst call.
        assert by_phase["analyst"]["calls"] == 1
        # Exactly one Research Manager, one Trader, one Portfolio (free text path).
        assert by_phase["research_manager"]["calls"] == 1
        assert by_phase["trader"]["calls"] == 1
        assert by_phase["portfolio"]["calls"] == 1
        # Exactly three risk analysts.
        assert by_phase["risk"]["calls"] == 3
        # TOTAL: analyst(1)+debate(2)+RM(1)+trader(1)+risk(3)+portfolio(1) = 9.
        assert whole["totals"]["calls"] == 9
        # Exact provider tokens: (100 in + 20 out) * 9 = 1080.
        assert whole["totals"]["tokens"] == 9 * 120
        assert whole["totals"]["input_tokens"] == 9 * 100
        assert whole["totals"]["output_tokens"] == 9 * 20
        # All calls carried provider telemetry: completeness is complete.
        assert whole["completeness"] == COMPLETENESS_COMPLETE
        # Provider-call count matches; no unknown-cost calls.
        assert whole["provider_token_call_count"] == 9
        assert whole["totals"]["unknown_cost_calls"] == 0

    def test_debate_call_counted_once_not_both_tracker_and_ledger(self, tmp_path):
        final, whole, ledger, rid, *_ = _run_full(tmp_path)
        # The debate_usage (checkpoint, tracker-derived) and the whole-run debate
        # phase must agree on the call count — the debate is not double-counted.
        debate_usage_calls = int((final.get("debate_usage") or {}).get("calls", 0))
        assert debate_usage_calls == whole["by_phase"]["debate"]["calls"] == 2

    def test_report_artifacts_and_whole_run_structure_agree(self, tmp_path):
        final, whole, ledger, rid, *_ = _run_full(tmp_path)
        # Attach the whole-run block exactly like propagate() does.
        final["whole_run_usage"] = whole
        out = tmp_path / "art"
        write_report_artifacts(final, SYMBOL, out)
        summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
        assert summary["execution_run_id"] == rid
        assert summary["whole_run_usage"]["totals"]["calls"] == 9
        assert summary["whole_run_usage"]["completeness"] == COMPLETENESS_COMPLETE
        # The consolidated report carries the same whole-run completeness line.
        from tradingagents.reporting import write_report_tree

        write_report_tree(final, SYMBOL, out)
        md = (out / "complete_report.md").read_text(encoding="utf-8")
        assert "Whole-run usage: 9 calls" in md
        assert f"completeness={COMPLETENESS_COMPLETE}" in md

    def test_failed_unknown_cost_makes_run_partial(self, tmp_path):
        # A failed/unknown-cost typed event makes the whole-run completeness
        # partial and is NEVER added as a zero-known token cost.
        from tradingagents.debate.usage_ledger import UsageLedger as UL

        rid = new_run_id(SYMBOL, TARGET, nonce="partial")
        ledger = UL(tmp_path / "u.db")
        ledger.begin_run(rid)
        ledger.reserve(run_id=rid, invocation_id="t1", phase="trader", speaker="Trader",
                       reserved_tokens=100, reserved_seconds=1.0)
        ledger.settle(run_id=rid, invocation_id="t1", status="success", phase="trader",
                      speaker="Trader", total_tokens=120, tokens_source="provider",
                      seconds=1.0, seconds_source="measured")
        ledger.reserve(run_id=rid, invocation_id="t2", phase="risk", speaker="Risk",
                       reserved_tokens=100, reserved_seconds=1.0)
        ledger.settle(run_id=rid, invocation_id="t2", status="failed", phase="risk",
                      speaker="Risk", total_tokens=None, tokens_source="unavailable",
                      unresolved=True)
        whole = aggregate_whole_run_usage(ledger.read_run_spend(rid).events)
        assert whole["completeness"] == COMPLETENESS_PARTIAL
        assert whole["totals"]["tokens"] == 120  # only the known call
        assert whole["totals"]["unknown_cost_calls"] == 1
        assert whole["unresolved_invocations"] >= 1

    def test_no_calls_is_unknown_never_zero_complete(self):
        whole = aggregate_whole_run_usage([])
        assert whole["completeness"] == COMPLETENESS_UNKNOWN
        assert whole["totals"]["calls"] == 0


class TestStructuredFallbackCounting:
    def test_structured_failure_then_freetext_is_two_attempts(self, tmp_path):
        rid = new_run_id(SYMBOL, TARGET, nonce="fb")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        cap = UsageCapture(run_id=rid, ledger=ledger)

        class _Structured:
            def invoke(self, prompt):
                raise RuntimeError("structured boom")

        class _Plain:
            def invoke(self, prompt):
                return _resp("rendered fallback", (30, 10))

        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                _Structured(), _Plain(), "prompt", lambda r: "x", "Trader"
            )
        assert text == "rendered fallback"
        spend = ledger.read_run_spend(rid)
        # Two counted attempts: the failed structured + the free-text retry.
        assert len(spend.events) == 2
        assert spend.events[0].status == "failed"
        assert spend.events[1].status == "success"
        assert spend.events[1].total_tokens == 40
        whole = aggregate_whole_run_usage(spend.events)
        assert whole["by_phase"]["trader"]["calls"] == 2
        # The failed structured attempt makes the run partial, not complete.
        assert whole["completeness"] == COMPLETENESS_PARTIAL

    def test_structured_pydantic_result_not_estimated_zero(self, tmp_path):
        rid = new_run_id(SYMBOL, TARGET, nonce="pj")
        ledger = UsageLedger(tmp_path / "u.db")
        ledger.begin_run(rid)
        cap = UsageCapture(run_id=rid, ledger=ledger)

        class _Result:
            # A Pydantic-like object: no ``.content``, no provider telemetry.

            def __init__(self):
                self.value = "BIG"

        class _Structured:
            def invoke(self, prompt):
                return _Result()

        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                _Structured(),
                None,
                "p" * 400,
                lambda r: "R" * 200,  # rendered output is 200 chars
                "Trader",
            )
        assert text == "R" * 200
        ev = ledger.read_run_spend(rid).events[0]
        # Output chars came from the rendered result (200), not 0: tokens>0.
        assert ev.total_tokens is not None and ev.total_tokens > 0
        assert ev.tokens_source == "estimated"  # no provider telemetry => estimate


# ---------------------------------------------------------------------------
# DEFAULT 4-analyst full graph run (mocked raw sentiment prefetch, no sockets).
# ---------------------------------------------------------------------------


def _mock_sentiment_prefetch(monkeypatch):
    """Mock the sentiment prefetch transports at the RAW source (no sockets)."""
    import tradingagents.agents.analysts.sentiment_analyst as sa

    monkeypatch.setattr(sa.get_news, "func", lambda *a, **k: "## news")
    monkeypatch.setattr(sa, "fetch_stocktwits_messages", lambda *a, **k: "## stocktwits")
    monkeypatch.setattr(sa, "fetch_reddit_posts", lambda *a, **k: "## reddit")


def _build_four_analyst_graph(quick, deep, *, config_override=None):
    return _build_four_analyst_workflow(quick, deep, config_override=config_override).compile()


def _build_four_analyst_workflow(quick, deep, *, config_override=None):
    tool_nodes = {key: ToolNode([]) for key in ("market", "social", "news", "fundamentals")}
    setup = GraphSetup(
        quick,
        deep,
        tool_nodes,
        ConditionalLogic(),
        data_quality_gate_factory=lambda: _stub_gate_node(),
        debate_termination_config=config_override,
    )
    return setup.setup_graph(("market", "social", "news", "fundamentals"))


def _run_four_analyst(tmp_path, monkeypatch, *, tokens=(100, 20), cfg=None):
    _mock_sentiment_prefetch(monkeypatch)
    rid = new_run_id(SYMBOL, TARGET, nonce="full4")
    ledger = UsageLedger(tmp_path / "usage.db")
    ledger.begin_run(rid)
    quick = _ScriptedLLM(_TURN, tokens)
    deep = _ScriptedLLM("Hold", tokens)
    cfg = cfg or DebateTerminationConfig.from_dict({"max_debate_rounds": 1})
    cap = UsageCapture(run_id=rid, ledger=ledger)
    cap.debate_config = cfg
    graph = _build_four_analyst_graph(quick, deep, config_override=cfg)
    with use_usage_capture(cap):
        final = graph.invoke(_initial_state(rid))
    whole = aggregate_whole_run_usage(ledger.read_run_spend(rid).events)
    return final, whole, ledger, rid, quick, deep


class TestFourAnalystWholeRun:
    def test_exact_twelve_calls_no_fallback(self, tmp_path, monkeypatch):
        # 4 analysts + 2 debate + RM + Trader + 3 risk + Portfolio = 12 logical
        # calls, each a single free-text/invoke attempt (no fallback).
        final, whole, ledger, rid, quick, deep = _run_four_analyst(tmp_path, monkeypatch)
        assert whole["by_phase"]["analyst"]["calls"] == 4
        assert whole["by_phase"]["debate"]["calls"] == 2
        assert whole["by_phase"]["research_manager"]["calls"] == 1
        assert whole["by_phase"]["trader"]["calls"] == 1
        assert whole["by_phase"]["risk"]["calls"] == 3
        assert whole["by_phase"]["portfolio"]["calls"] == 1
        assert whole["totals"]["calls"] == 12
        assert whole["totals"]["tokens"] == 12 * (100 + 20)
        assert whole["completeness"] == COMPLETENESS_COMPLETE
        # The ledger total equals the INDEPENDENT raw model-invocation counter
        # (both direct .invoke and .bind_tools chain calls), proving no model
        # call is missing from the ledger.
        raw_calls = quick.total_model_calls + deep.total_model_calls
        assert whole["totals"]["calls"] == raw_calls == 12

    def test_real_fallback_increments_exactly_once(self, tmp_path, monkeypatch):
        # A structured-output attempt that fails and falls back to free text is a
        # SECOND counted attempt for that agent; the total is exactly +1.
        _mock_sentiment_prefetch(monkeypatch)
        rid = new_run_id(SYMBOL, TARGET, nonce="full4fb")
        ledger = UsageLedger(tmp_path / "usage.db")
        ledger.begin_run(rid)

        class _StructuredFailsThenText:
            """A deep model whose structured attempt raises, then free text works."""

            def __init__(self):
                self.invoke_calls = 0
                self.bind_invoke_calls = 0
                self._structured_invoke_calls = 0

            @property
            def total_model_calls(self):
                return self.invoke_calls + self.bind_invoke_calls + self._structured_invoke_calls

            def with_structured_output(self, *a, **k):
                owner = self

                class _S:
                    def invoke(self, prompt):
                        owner._structured_invoke_calls += 1
                        raise RuntimeError("structured miss")

                return _S()

            def bind_tools(self, tools):
                def _chain(m):
                    self.bind_invoke_calls += 1
                    return _resp("Hold", (100, 20))

                return RunnableLambda(_chain)

            def invoke(self, prompt):
                self.invoke_calls += 1
                return _resp("Hold", (100, 20))

        quick = _ScriptedLLM(_TURN, (100, 20))
        deep = _StructuredFailsThenText()
        cfg = DebateTerminationConfig.from_dict({"max_debate_rounds": 1})
        cap = UsageCapture(run_id=rid, ledger=ledger)
        cap.debate_config = cfg
        graph = _build_four_analyst_graph(quick, deep, config_override=cfg)
        with use_usage_capture(cap):
            graph.invoke(_initial_state(rid))
        whole = aggregate_whole_run_usage(ledger.read_run_spend(rid).events)
        # A structured→free-text fallback is honestly counted, and when the failed
        # structured attempt is unresolved spend the caller's own fallback is
        # refused (deterministic template) so it does not retry the reserve.
        # Pin the EXACT observed total and prove it equals the INDEPENDENT raw
        # model-invocation counter (no missing/extra ledger rows).
        exact = whole["totals"]["calls"]
        assert exact == 13
        assert exact == quick.total_model_calls + deep.total_model_calls
        # At least one structured attempt failed => honest partial completeness.
        assert whole["completeness"] == COMPLETENESS_PARTIAL

    def test_report_uses_run_graph_produced_state_not_manual_attach(self, tmp_path, monkeypatch):
        """Exercise the PUBLIC _run_graph path so the report reads the whole-run
        block the production code attached (not a manual attach)."""
        from unittest.mock import MagicMock

        from tradingagents.graph.checkpointer import get_checkpointer, thread_id
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        _mock_sentiment_prefetch(monkeypatch)
        rid = new_run_id(SYMBOL, TARGET, nonce="full4pub")
        ledger_path = tmp_path / "usage.db"
        ledger = UsageLedger(ledger_path)
        ledger.begin_run(rid)
        quick = _ScriptedLLM(_TURN, (100, 20))
        deep = _ScriptedLLM("Hold", (100, 20))
        cfg = DebateTerminationConfig.from_dict({"max_debate_rounds": 1})
        data_dir = str(tmp_path / "ckpt")
        tid = thread_id(SYMBOL, TARGET)

        with get_checkpointer(data_dir, SYMBOL) as saver:
            g = _build_four_analyst_workflow(quick, deep, config_override=cfg).compile(checkpointer=saver)
            graph = object.__new__(TradingAgentsGraph)
            graph.config = {
                "results_dir": str(tmp_path),
                "checkpoint_enabled": True,
                "debate_termination": {"max_debate_rounds": 1},
            }
            graph.debug = False
            graph._resuming = False
            graph.graph = g
            graph.propagator = MagicMock()
            graph.propagator.get_graph_args.return_value = {
                "config": {"configurable": {"thread_id": tid}}
            }
            graph.memory_log = MagicMock()
            graph.ticker = SYMBOL
            graph.log_states_dict = {}
            graph.signal_processor = MagicMock()
            graph.signal_processor.process_signal.return_value = "Hold"
            graph.selected_analysts = ("market", "social", "news", "fundamentals")
            graph._log_state = lambda *a, **k: None
            graph.record_decision = lambda *a, **k: None
            graph.clear_checkpoint_on_success = lambda *a, **k: None
            graph.create_run_state = lambda *a, **k: _initial_state(rid)
            final, signal = TradingAgentsGraph._run_graph(
                graph, SYMBOL, TARGET, asset_type="stock",
                checkpoint_thread_id=tid,
            )
        # The production _run_graph attached whole_run_usage (no manual attach).
        assert final.get("whole_run_usage")
        assert final["whole_run_usage"]["totals"]["calls"] == 12
        assert final.get("run_id") == rid
        # And the report artifacts read that block.
        out = tmp_path / "art"
        write_report_artifacts(final, SYMBOL, out)
        summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
        assert summary["whole_run_usage"]["totals"]["calls"] == 12
        assert summary["execution_run_id"] == rid
