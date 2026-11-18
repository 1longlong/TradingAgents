"""Defect-2 (ADR-009 amendment): structured-output calls retain their RAW
transport usage for honest whole-run accounting, while callers keep the parsed
typed output — with NO second model call and NO false provider claims.

Root cause pinned here: the structured binding returned a bare Pydantic object
with no ``usage_metadata``, so ``instrumented_model_call`` settled an ESTIMATE
even when the provider reported real usage to the raw response. The fix binds
with ``include_raw=True`` (one call), settles usage from the raw ``AIMessage``,
and renders/caps the parsed object.

Covered offline (real-shaped ``AIMessage`` token metadata; mocked models, NO
network):

- RM / Trader / PM / Sentiment schemas: raw usage settled exact (provider), the
  rendered output is the parsed typed object's render, exactly ONE invocation;
- a provider that rejects ONLY ``include_raw`` (NotImplementedError / TypeError)
  is re-bound WITHOUT it (binding-only, one invocation) and stays typed+estimated;
  a provider that rejects all structured output uses free text;
- a parser error WITH known raw usage is settled with that exact usage BEFORE the
  free-text fallback (two distinct attempts, atomic admission preserved);
- a sanitizer error / render error with known raw usage is still settled exact
  (no unknown-cost, no double count);
- an unknown transport exception stays unknown (never zero / never provider);
- the whole-run AGGREGATE labels a provider+estimated mix as ``mixed`` (report
  only), keeps all known tokens, and never writes ``mixed`` as a per-call source;
- concurrent/idempotent settlement and the degraded confidence cap 0.60 regressions.

Traceability: NFR-BUD-001, NFR-AUD-001, FR-DDT-003, NFR-BC-001, INV-7.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import (
    PortfolioDecision,
    ResearchPlan,
    SentimentReport,
    TraderProposal,
    render_pm_decision,
    render_research_plan,
    render_sentiment_report,
    render_trader_proposal,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.debate.budget import (
    SOURCE_MIXED,
    aggregate_whole_run_usage,
)
from tradingagents.debate.confidence_policy import cap_typed_confidence
from tradingagents.debate.usage_capture import UsageCapture, use_usage_capture
from tradingagents.debate.usage_ledger import UsageLedger, new_run_id

SYMBOL = "COF"
TARGET = "2026-05-13"


def _ai(content: str, tokens: tuple[int, int]) -> AIMessage:
    inp, out = tokens
    msg = AIMessage(content=content)
    msg.usage_metadata = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    msg.response_metadata = {}
    return msg


def _capture(tmp_path, nonce):
    rid = new_run_id(SYMBOL, TARGET, nonce=nonce)
    ledger = UsageLedger(tmp_path / f"{nonce}.db")
    ledger.begin_run(rid)
    return UsageCapture(run_id=rid, ledger=ledger), ledger, rid


class _RawStructured:
    """A structured binding that returns an include_raw envelope (one call)."""

    def __init__(self, parsed, tokens, *, parsing_error=None):
        self._parsed = parsed
        self._tokens = tokens
        self._parsing_error = parsing_error
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return {
            "raw": _ai("raw body", self._tokens),
            "parsed": self._parsed,
            "parsing_error": self._parsing_error,
        }


class _Plain:
    def __init__(self, tokens=(11, 7)):
        self._tokens = tokens
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return _ai("plain fallback", self._tokens)


# ---------------------------------------------------------------------------
# Real per-role schemas: raw usage settled exact; parsed render preserved.
# ---------------------------------------------------------------------------


class TestPerRoleRawUsage:
    @pytest.mark.parametrize(
        "parsed, render, tokens",
        [
            (
                ResearchPlan(recommendation="Hold", rationale="r", strategic_actions="a"),
                render_research_plan,
                (120, 40),
            ),
            (
                TraderProposal(action="Hold", reasoning="r"),
                render_trader_proposal,
                (90, 30),
            ),
            (
                PortfolioDecision(rating="Hold", executive_summary="s", investment_thesis="t"),
                render_pm_decision,
                (200, 60),
            ),
            (
                SentimentReport(
                    overall_band="Neutral", overall_score=5.0, confidence="low", narrative="n"
                ),
                render_sentiment_report,
                (70, 20),
            ),
        ],
    )
    def test_raw_usage_settled_exact_and_render_is_parsed(self, tmp_path, parsed, render, tokens):
        cap, ledger, rid = _capture(tmp_path, "role")
        structured = _RawStructured(parsed, tokens)
        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(structured, None, "prompt", render, "Trader")
        # The rendered output is exactly the parsed object's render (typed path).
        assert text == render(parsed)
        ev = ledger.read_run_spend(rid).events[0]
        # Provider usage came from the RAW AIMessage, not an estimate.
        assert ev.tokens_source == "provider"
        assert ev.total_tokens == tokens[0] + tokens[1]
        assert ev.input_tokens == tokens[0]
        assert ev.output_tokens == tokens[1]
        assert structured.calls == 1  # exactly one model call


# ---------------------------------------------------------------------------
# Binding fallback: include_raw rejection re-binds WITHOUT it (one invocation).
# ---------------------------------------------------------------------------


class _RejectIncludeRawOnly:
    """Works with include_raw=False; raises the given error for include_raw=True."""

    def __init__(self, exc):
        self._exc = exc
        self.bind_calls = 0
        self.structured_invocations = 0
        self.parsed = TraderProposal(action="Hold", reasoning="r")

    def with_structured_output(self, schema, *, include_raw=False, **kw):
        self.bind_calls += 1
        if include_raw:
            raise self._exc
        owner = self

        class _Bound:
            def invoke(self, prompt):
                owner.structured_invocations += 1
                return owner.parsed  # legacy typed result (no usage metadata)

        return _Bound()


class _Unsupported:
    def with_structured_output(self, schema, *, include_raw=False, **kw):
        raise NotImplementedError("no structured output")


class TestBindingFallback:
    @pytest.mark.parametrize(
        "exc", [NotImplementedError("include_raw rejected"), TypeError("bad kw")]
    )
    def test_include_raw_rejection_rebinds_without_it_no_freetext(self, tmp_path, exc):
        cap, ledger, rid = _capture(tmp_path, "bindfb")
        llm = _RejectIncludeRawOnly(exc)
        bound = bind_structured(llm, TraderProposal, "Trader")
        assert bound is not None, "must re-bind the legacy typed path, not free text"
        assert llm.bind_calls == 2  # include_raw attempt + plain rebind (no model call)
        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                bound, _Plain(), "p", render_trader_proposal, "Trader"
            )
        assert text == render_trader_proposal(llm.parsed)
        assert llm.structured_invocations == 1  # exactly ONE model invocation
        ev = ledger.read_run_spend(rid).events[0]
        # Legacy typed result has no usage -> honest estimate, never false provider.
        assert ev.tokens_source == "estimated"
        assert ev.total_tokens is not None and ev.total_tokens > 0

    def test_truly_unsupported_returns_none_for_freetext(self):
        assert bind_structured(_Unsupported(), TraderProposal, "Trader") is None


# ---------------------------------------------------------------------------
# Parser error WITH known raw usage: settled exact BEFORE fallback; 2 attempts.
# ---------------------------------------------------------------------------


class TestParserErrorWithKnownUsage:
    def test_parsing_error_known_usage_settled_before_fallback(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "parseerr")
        structured = _RawStructured(parsed=None, tokens=(150, 50), parsing_error="bad json")
        plain = _Plain((21, 9))
        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                structured, plain, "p", render_trader_proposal, "Trader"
            )
        assert text == "plain fallback"
        events = ledger.read_run_spend(rid).events
        assert len(events) == 2  # structured attempt + free-text retry (each once)
        structured_ev, fallback_ev = events
        # The parser-miss structured attempt is settled with the REAL raw usage.
        assert structured_ev.status == "success"
        assert structured_ev.tokens_source == "provider"
        assert structured_ev.total_tokens == 200
        assert fallback_ev.tokens_source == "provider"
        assert fallback_ev.total_tokens == 30
        assert structured.calls == 1 and plain.calls == 1


# ---------------------------------------------------------------------------
# Sanitizer / render error AFTER a known raw response: settled exact, not unknown.
# ---------------------------------------------------------------------------


class TestDownstreamErrorKeepsKnownUsage:
    def test_sanitizer_error_known_usage_settled_exact_then_fallback(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "sanerr")
        structured = _RawStructured(
            TraderProposal(action="Hold", reasoning="r"), tokens=(100, 20)
        )
        plain = _Plain((5, 5))

        def _boom(_result):
            raise RuntimeError("sanitizer exploded")

        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                structured, plain, "p", render_trader_proposal, "Trader", sanitize_result=_boom
            )
        assert text == "plain fallback"
        events = ledger.read_run_spend(rid).events
        assert len(events) == 2  # settled once each; no doubled count
        first = events[0]
        # Known raw usage: the sanitizer failure did NOT turn it into unknown-cost.
        assert first.status == "success"
        assert first.tokens_source == "provider"
        assert first.total_tokens == 120
        assert first.unresolved is False

    def test_render_error_known_usage_settled_exact_then_fallback(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "rnderr")
        structured = _RawStructured(
            TraderProposal(action="Hold", reasoning="r"), tokens=(80, 20)
        )
        plain = _Plain((5, 5))

        def _render_boom(_result):
            raise RuntimeError("render exploded")

        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                structured, plain, "p", _render_boom, "Trader"
            )
        assert text == "plain fallback"
        events = ledger.read_run_spend(rid).events
        assert len(events) == 2
        assert events[0].status == "success"
        assert events[0].tokens_source == "provider"
        assert events[0].total_tokens == 100


# ---------------------------------------------------------------------------
# Unknown transport failure stays unknown (never zero / never provider).
# ---------------------------------------------------------------------------


class TestUnknownTransportFailure:
    def test_transport_exception_is_failed_unknown_and_fallback_counted(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "unk")
        plain = _Plain((7, 3))

        class _Raising:
            def invoke(self, prompt):
                raise ConnectionError("transport down")  # unknown if it billed

        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                _Raising(), plain, "p", render_trader_proposal, "Trader"
            )
        assert text == "plain fallback"
        events = ledger.read_run_spend(rid).events
        assert len(events) == 2
        first, second = events
        assert first.status == "failed"
        assert first.unresolved is True
        assert first.total_tokens is None  # unknown, NOT zero
        assert first.tokens_source == "unavailable"
        assert second.tokens_source == "provider"


# ---------------------------------------------------------------------------
# Mixed aggregate label is report-only; known tokens not omitted.
# ---------------------------------------------------------------------------


class TestMixedAggregateLabel:
    def test_mixed_total_label_not_provider_and_keeps_known_tokens(self, tmp_path):
        # One provider structured call + one estimated legacy call + one unknown.
        cap, ledger, rid = _capture(tmp_path, "mixed")
        structured = _RawStructured(
            TraderProposal(action="Hold", reasoning="r"), tokens=(200, 50)
        )
        with use_usage_capture(cap):
            invoke_structured_or_freetext(
                structured, None, "p", render_trader_proposal, "Trader"
            )
        # Legacy typed result (no raw) -> estimated.
        cap2 = cap

        class _Legacy:
            def invoke(self, prompt):
                return TraderProposal(action="Hold", reasoning="x")

        with use_usage_capture(cap2):
            invoke_structured_or_freetext(
                _Legacy(), None, "p", render_trader_proposal, "Portfolio Manager"
            )
        whole = aggregate_whole_run_usage(ledger.read_run_spend(rid).events)
        totals = whole["totals"]
        # Provider contributed 250; estimated legacy added its own known estimate;
        # the aggregate label must be mixed (never provider), tokens not dropped.
        assert totals["tokens_source"] == SOURCE_MIXED
        assert totals["tokens"] >= 250
        assert totals["estimated"] is True
        assert whole["completeness"] == "partial"

    def test_all_provider_run_stays_provider(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "allprov")
        with use_usage_capture(cap):
            invoke_structured_or_freetext(
                _RawStructured(TraderProposal(action="Hold", reasoning="r"), (10, 5)),
                None, "p", render_trader_proposal, "Trader",
            )
        whole = aggregate_whole_run_usage(ledger.read_run_spend(rid).events)
        assert whole["totals"]["tokens_source"] == "provider"

    def test_mixed_never_accepted_as_per_call_source(self, tmp_path):
        # ``mixed`` must never be storable as a per-call provider source.
        from tradingagents.debate.usage_ledger import _ALLOWED_TOKEN_SOURCES

        assert SOURCE_MIXED not in _ALLOWED_TOKEN_SOURCES


# ---------------------------------------------------------------------------
# Concurrency / idempotency: each actual attempt settles exactly once.
# ---------------------------------------------------------------------------


class TestConcurrencyIdempotency:
    def test_repeated_settle_same_id_is_idempotent(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "idem")
        with use_usage_capture(cap):
            invoke_structured_or_freetext(
                _RawStructured(TraderProposal(action="Hold", reasoning="r"), (40, 10)),
                None, "p", render_trader_proposal, "Trader",
            )
        events = ledger.read_run_spend(rid).events
        assert len(events) == 1
        # Re-reading the ledger returns the same single row (no double add).
        assert len(ledger.read_run_spend(rid).events) == 1
        assert events[0].total_tokens == 50

    def test_two_rounds_settle_each_once(self, tmp_path):
        cap, ledger, rid = _capture(tmp_path, "two")
        with use_usage_capture(cap):
            for _ in range(2):
                invoke_structured_or_freetext(
                    _RawStructured(TraderProposal(action="Hold", reasoning="r"), (30, 10)),
                    None, "p", render_trader_proposal, "Trader",
                )
        whole = aggregate_whole_run_usage(ledger.read_run_spend(rid).events)
        assert whole["by_phase"]["trader"]["calls"] == 2
        assert whole["totals"]["tokens"] == 2 * 40


# ---------------------------------------------------------------------------
# Confidence cap 0.60 still sees the EXACT raw parsed value (ADR-011 unchanged).
# ---------------------------------------------------------------------------


class TestConfidenceCapRegression:
    def test_typed_cap_on_exact_raw_before_render(self, tmp_path):
        # A degraded-run state caps the typed numeric confidence at its EXACT raw
        # value BEFORE the lossy 2dp render (defect-2 must not disturb this).
        cap, ledger, rid = _capture(tmp_path, "cap")
        parsed = TraderProposal(action="Hold", reasoning="r", confidence=0.954321)
        sink: list[dict] = []
        state = {
            "data_quality_verdict": "degraded",
            "data_quality_gate_decision": {"decision": "degraded"},
        }

        def _sanitize(result):
            return cap_typed_confidence(
                result, state, source="Trader", boundary="trader_typed", sink=sink
            )

        with use_usage_capture(cap):
            text = invoke_structured_or_freetext(
                _RawStructured(parsed, (50, 10)),
                None, "p", render_trader_proposal, "Trader", sanitize_result=_sanitize,
            )
        # Rendered effective confidence is capped to 0.60 (from the exact raw).
        assert "**Confidence**: 0.60" in text
        assert sink and sink[0]["raw_value"] == 0.954321
        # Usage still settled exact from raw (provider), unaffected by capping.
        ev = ledger.read_run_spend(rid).events[0]
        assert ev.tokens_source == "provider"
        assert ev.total_tokens == 60


# ---------------------------------------------------------------------------
# PUBLIC TradingAgentsGraph._run_graph end-to-end: real production gate, a
# role-aware raw-envelope model, a real active collector + durable ledger, NO
# manually attached usage/origins. Proves the actual node/public path (not just
# the shared utility) settles exact provider usage and yields 5 market origins.
# ---------------------------------------------------------------------------

import pandas as pd  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402

import tradingagents.dataflows.market_data_validator as _mdv  # noqa: E402
from tradingagents.agents.managers.portfolio_manager import PortfolioDecision  # noqa: E402
from tradingagents.agents.managers.research_manager import ResearchPlan  # noqa: E402
from tradingagents.agents.trader.trader import TraderProposal  # noqa: E402
from tradingagents.debate.config import DebateTerminationConfig  # noqa: E402
from tradingagents.evidence.ingest import get_active_collector, use_collector  # noqa: E402
from tradingagents.evidence.origin import ORIGIN_STATE_KEY  # noqa: E402
from tradingagents.graph.checkpointer import get_checkpointer, thread_id  # noqa: E402
from tradingagents.graph.conditional_logic import ConditionalLogic  # noqa: E402
from tradingagents.graph.data_quality_gate import create_data_quality_gate_node  # noqa: E402
from tradingagents.graph.propagation import Propagator  # noqa: E402
from tradingagents.graph.setup import GraphSetup  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402
from tradingagents.report_artifacts import write_report_artifacts  # noqa: E402

_SYM = "NVDA"
_DAY = "2026-05-13"
_TURN = "Argument.\nDEBATE_METADATA: stance=Buy; confidence=0.7; cited=; new_claims=;"


def _fixed_market_df():
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame({
        "Date": dates, "Open": [c - 0.5 for c in closes], "High": [c + 1.0 for c in closes],
        "Low": [c - 1.0 for c in closes], "Close": closes,
        "Volume": [1_000_000 + i for i in range(len(dates))],
    })


def _role_aware_deep(tokens_by_role):
    """A deep model whose structured calls return a raw-envelope carrying usage.

    Each schema gets its OWN token pair so per-role totals are independent.
    Counts every invocation so the test can compare against an independent counter.
    """
    parsed_by_name = {
        "ResearchPlan": ResearchPlan(recommendation="Hold", rationale="r", strategic_actions="a"),
        "TraderProposal": TraderProposal(action="Hold", reasoning="r"),
        "PortfolioDecision": PortfolioDecision(
            rating="Hold", executive_summary="s", investment_thesis="t"
        ),
    }

    class _Deep:
        def __init__(self):
            self.invocations = 0

        def with_structured_output(self, schema, *, include_raw=False, **kw):
            role = schema.__name__
            inp, out = tokens_by_role[role]

            class _Bound:
                def invoke(self, prompt):
                    self_outer.invocations += 1
                    return {
                        "raw": _ai("raw", (inp, out)),
                        "parsed": parsed_by_name[role],
                        "parsing_error": None,
                    }

            self_outer = self
            return _Bound()

        def bind_tools(self, tools):
            def _chain(m):
                self.invocations += 1
                return _ai(_TURN, (30, 10))

            return RunnableLambda(_chain)

        def invoke(self, prompt):
            self.invocations += 1
            return _ai("Hold", (30, 10))

    return _Deep()


def _quick():
    class _Quick:
        def __init__(self):
            self.invocations = 0

        def with_structured_output(self, *a, **k):
            return None  # analysts/risk use free text

        def bind_tools(self, tools):
            def _chain(m):
                self.invocations += 1
                return _ai(_TURN, (20, 8))

            return RunnableLambda(_chain)

        def invoke(self, prompt):
            self.invocations += 1
            return _ai(_TURN, (20, 8))

    return _Quick()


class TestPublicPropagateEndToEnd:
    def test_public_run_graph_exact_usage_and_five_origins(self, tmp_path, monkeypatch):
        # Real production gate over a mocked RAW OHLCV source (no network).
        monkeypatch.setattr(_mdv, "load_ohlcv", lambda s, d, fill_gaps=True: _fixed_market_df())
        # Sentiment prefetch used by the real sentiment analyst: mock raw source.
        import tradingagents.agents.analysts.sentiment_analyst as sa

        monkeypatch.setattr(sa.get_news, "func", lambda *a, **k: "## news")
        monkeypatch.setattr(sa, "fetch_stocktwits_messages", lambda *a, **k: "## st")
        monkeypatch.setattr(sa, "fetch_reddit_posts", lambda *a, **k: "## rd")

        per_role = {
            "ResearchPlan": (120, 40),
            "PortfolioDecision": (200, 60),
        }
        quick = _quick()
        deep = _role_aware_deep(per_role)
        cfg = DebateTerminationConfig.from_dict({"max_debate_rounds": 1})
        tool_nodes = {k: ToolNode([]) for k in ("market", "social", "news", "fundamentals")}

        def gate_factory():
            return create_data_quality_gate_node(now_provider=lambda: "2026-05-13T12:00:00Z")
        setup = GraphSetup(
            quick, deep, tool_nodes, ConditionalLogic(),
            data_quality_gate_factory=gate_factory,
            debate_termination_config=cfg,
        )
        workflow = setup.setup_graph(("market", "social", "news", "fundamentals"))

        # _run_graph opens its OWN durable ledger under the resolved execution
        # identity; we do NOT pre-bind a capture/ledger (no manual attach).
        tid = thread_id(_SYM, _DAY)
        memory_path = tmp_path / "memory.md"

        with get_checkpointer(str(tmp_path / "ckpt"), _SYM) as saver:
            g = workflow.compile(checkpointer=saver)
            graph = object.__new__(TradingAgentsGraph)
            graph.config = {
                "results_dir": str(tmp_path), "checkpoint_enabled": True,
                "debate_termination": {"max_debate_rounds": 1},
            }
            graph.debug = False
            graph._resuming = False
            graph.graph = g
            graph.propagator = Propagator()
            graph.propagator.get_graph_args = lambda callbacks=None: {
                "config": {"configurable": {"thread_id": tid}}
            }
            from tradingagents.agents.utils.memory import TradingMemoryLog
            graph.memory_log = TradingMemoryLog({"memory_log_path": str(memory_path)})
            graph.ticker = _SYM
            graph.log_states_dict = {}
            graph.signal_processor = object.__new__(type("SP", (), {}))
            graph.selected_analysts = ("market", "social", "news", "fundamentals")
            graph._log_state = lambda *a, **k: None

            # Exercise the REAL memory store (real TradingMemoryLog, no mock): the
            # production record_decision ultimately calls memory_log.store_decision.
            def _record_decision(company_name, trade_date, final_state):
                decision = final_state.get("final_trade_decision")
                if decision:
                    graph.memory_log.store_decision(
                        ticker=company_name, trade_date=trade_date,
                        final_trade_decision=decision, blocked=False,
                    )

            graph.record_decision = _record_decision
            graph.clear_checkpoint_on_success = lambda *a, **k: None
            def _create_run_state(company_name, trade_date, asset_type="stock", portfolio=None, **kw):
                state = Propagator().create_initial_state(_SYM, _DAY, asset_type="stock")
                state["run_id"] = kw.get("run_id")
                if kw.get("usage_ledger_path"):
                    state["usage_ledger_path"] = kw["usage_ledger_path"]
                return state

            graph.create_run_state = _create_run_state
            # Real module-level process_signal returns a rating string.
            graph.process_signal = lambda text: "Hold"

            # Real active collector; _run_graph binds its own durable usage ledger.
            with use_collector(_SYM, _DAY):
                final, signal = TradingAgentsGraph._run_graph(
                    graph, _SYM, _DAY, asset_type="stock", checkpoint_thread_id=tid
                )

        # 5 real market evidence records with typed origins present in final state
        # (the Defect-1 live shape: active collector must not erase them).
        assert len(final["data_quality_evidence_records"]) == 5
        assert len(final[ORIGIN_STATE_KEY]) == 5
        assert get_active_collector() is None

        # Exact usage: the ledger total equals the INDEPENDENT invocation counter.
        whole = final["whole_run_usage"]
        independent = quick.invocations + deep.invocations
        assert whole["totals"]["calls"] == independent
        # The structured roles (RM + PM use the deep model; Trader/Sentiment are
        # free-text on the quick model) settle with EXACT provider usage from the
        # raw envelope — not estimates.
        assert whole["by_phase"]["research_manager"]["tokens"] == sum(per_role["ResearchPlan"])
        assert whole["by_phase"]["research_manager"]["tokens_source"] == "provider"
        assert whole["by_phase"]["portfolio"]["tokens"] == sum(per_role["PortfolioDecision"])
        assert whole["by_phase"]["portfolio"]["tokens_source"] == "provider"
        # The Trader is a free-text (quick) call: honest, and counted once.
        assert whole["by_phase"]["trader"]["calls"] == 1

        # Report artifacts read the whole_run_usage the production path attached.
        out = tmp_path / "art"
        write_report_artifacts(final, _SYM, out)
        summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
        assert summary["whole_run_usage"]["totals"]["calls"] == independent
        # The run_summary names the SAME execution identity the production path
        # resolved and stamped on state (single source of truth).
        assert summary["execution_run_id"] == final["run_id"]
        # The memory log recorded the decision (real instance, no mock).
        assert memory_path.exists() and _SYM in memory_path.read_text(encoding="utf-8")

        # Cap 0.60 unchanged: the typed cap still sees the exact raw parsed value
        # (verified directly, independent of the pipeline).
        capped = cap_typed_confidence(
            TraderProposal(action="Hold", reasoning="r", confidence=0.954321),
            {"data_quality_verdict": "degraded",
             "data_quality_gate_decision": {"decision": "degraded"}},
            source="Trader", boundary="trader_typed",
        )
        assert capped.confidence == 0.60
