"""Merge-integration contracts between the release and token-observability lines.

This module pins the properties that made merging branch
``feature/token-observability`` into the release line safe. No new product
behaviour is introduced here: each test proves that an invariant of ONE branch
survives the combined tree, so a later edit cannot quietly restore one side and
drop the other.

Coverage
--------
1. **Single-pass transport accounting.** N outbound model requests through the
   single-pass loop settle as exactly N invocations; provider usage is preserved;
   a missing usage figure is never reported as ``0``; a budget denial propagates
   without an unauthorized fallback request.
2. **Binding settlement.** ``_with_settlement`` refuses a wrapper that does not
   actually carry the settlement callback, so the call is settled around
   ``invoke`` instead of being dropped from the accounting.
3. **``include_raw`` classification.** Only an ``include_raw``-shaped rejection
   is downgraded to the plain binding; a genuine binding defect propagates.
4. **Estimate-only attempts.** A successful binding with no raw usage is
   reported as a *success* plus an estimate, never as a fallback.
5. **GraphSetup compatibility.** The release keyword arguments and the feature
   ``config=`` argument are both accepted, the positional call stays valid, and
   the evidence wrapper composes around the analyst instead of replacing it.
6. **Analyst factories.** ``create_news_analyst`` accepts the merged switch set
   and every production call site passes a supported argument list.
7. **News evidence capture.** The Finnhub feed records a source attempt on every
   path that asked the provider, including the ones that raise.

All tests are offline: model bindings, HTTP transports and the evidence
collector are imported fakes. Traceability: FR-DQG-004, NFR-AUD-001,
NFR-DET-001, NFR-BC-001 (see ``docs/architecture/trace-matrix.md``).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tradingagents.agents.utils.structured import (
    UsageSettlementHandler,
    _call_schema_binding,
    _with_settlement,
    bind_structured,
    finalize_single_pass,
    run_data_tools,
)
from tradingagents.dataflows import finnhub_news
from tradingagents.debate.usage_capture import (
    BudgetDeniedError,
    UsageCapture,
    use_usage_capture,
)
from tradingagents.debate.usage_ledger import UsageLedger
from tradingagents.evidence.ingest import get_active_collector, use_collector
from tradingagents.observability import AGENT_UNATTRIBUTED

SYMBOL = "AAPL"
TARGET = "2026-05-13"


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _ai(content="", *, tool_calls=None, tokens=None):
    from langchain_core.messages import AIMessage

    usage = None
    if tokens is not None:
        usage = {
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
            "total_tokens": tokens[0] + tokens[1],
        }
    return AIMessage(content=content, tool_calls=list(tool_calls or []), usage_metadata=usage)


class _ScriptedChat(BaseChatModel):
    """A real chat model: it dispatches the callbacks its binding carries.

    A generic ``RunnableLambda`` never calls a chat model's callbacks, so the
    settlement handler would be attached but never fire. The production binding
    is a chat model, so the double must be one too.
    """

    script: list = []
    cursor: int = 0

    @property
    def _llm_type(self):
        return "scripted-merge"

    def _next(self):
        message = self.script[min(self.cursor, len(self.script) - 1)]
        self.cursor += 1
        return message

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _envelope(self):
        return {"raw": self._next(), "parsed": None, "parsing_error": None}

    def _wrap(self, producer):
        """Return a chat-model runnable whose one request yields ``producer()``.

        The structured binding must still BE a chat model: only a chat model
        dispatches the chat-model callbacks a settlement handler listens on.
        """

        class _Bound(BaseChatModel):
            envelope: dict | None = None

            @property
            def _llm_type(self):
                return "scripted-merge-bound"

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                # Reached only when called as a plain model (e.g. the free-text
                # retry). The include_raw envelope path is ``invoke`` below.
                produced = producer()
                self.envelope = produced
                message = produced.get("raw") if isinstance(produced, dict) else produced
                return ChatResult(generations=[ChatGeneration(message=message)])

            def invoke(self, input, config=None, **kwargs):  # noqa: A002
                # Run exactly one request through the chat-model callback path
                # (start -> end), as the real provider does, and hand the
                # include_raw ENVELOPE back so a settlement handler sees exactly
                # one start/end pair for this outbound attempt.
                from langchain_core.callbacks.manager import CallbackManager

                callbacks = (config or {}).get("callbacks")
                if not isinstance(callbacks, (list, tuple)):
                    callbacks = None
                manager = CallbackManager.configure(
                    inheritable_callbacks=callbacks,
                    inheritable_metadata=(config or {}).get("metadata"),
                )
                messages = input if isinstance(input, list) else [
                    HumanMessage(content=str(input))]
                produced = producer()
                self.envelope = produced
                message = produced.get("raw") if isinstance(produced, dict) else produced
                run_manager = manager.on_chat_model_start(
                    self._identifying_params | {"_type": self._llm_type},
                    [messages],
                )[0]
                result = ChatResult(generations=[ChatGeneration(message=message)])
                try:
                    run_manager.on_llm_end(result)
                except BaseException as exc:  # noqa: BLE001
                    # A budget refusal surfaces as an error on the run's handler
                    # (production would do exactly this); never report success.
                    run_manager.on_llm_error(exc)
                    raise
                return {"raw": message, "parsed": None, "parsing_error": None}

        return _Bound()

    def with_structured_output(self, schema, **kwargs):
        model = self

        def _produce():
            return model._envelope()

        return self._wrap(_produce)

    def bind_tools(self, tools, **kwargs):
        model = self

        def _produce():
            return model._next()

        return self._wrap(_produce)


class _SchemaAdapter:
    """The binding a provider would hand to the single-pass loop.

    ``bind_tools(tools + [schema])`` returns the caller's scripted transport, so
    the *schema* tool call the model emits reaches the loop as it does live: the
    loop reads ``llm.bind_tools`` and the inner transport is what is billed.
    """

    config = None

    def __init__(self, transport):
        self._transport = transport

    def bind_tools(self, tools, **kwargs):
        return self._transport


def _run_single_pass(binding, tools):
    return finalize_single_pass(
        llm=_SchemaAdapter(binding),
        structured_llm=binding,
        prompt=_prompt(),
        messages=[("human", "Analyze AAPL")],
        tools=tools,
        schema=_schema(),
        render=_render(),
        agent_name="Market Analyst",
        run_tools=run_data_tools(tools),
    )


def _capture(tmp_path, nonce):
    ledger = UsageLedger(tmp_path / f"{nonce}.db")
    run_id = f"run-{nonce}"
    ledger.begin_run(run_id)
    return UsageCapture(run_id=run_id, ledger=ledger), ledger, run_id


class _NoBudgetLeft:
    """A debate budget whose every optional call is unaffordable."""

    def __init__(self):
        from tradingagents.debate.config import DebateTerminationConfig

        self._config = DebateTerminationConfig(
            enabled=True,
            max_calls=1,
            max_tokens=1,
            max_time=0.0,
            reserved_summary_tokens=0,
            reserved_summary_seconds=0.0,
            next_round_estimate_tokens=10,
            next_round_estimate_seconds=0.0,
        )

    def __getattr__(self, name):
        return getattr(self._config, name)


def _data_call(call_id="t1"):
    return {
        "name": "get_stock_data",
        "type": "tool_call",
        "id": call_id,
        "args": {"symbol": SYMBOL, "start_date": "2026-05-01", "end_date": TARGET},
    }


def _schema_call():
    return {
        "name": "MarketAnalystReport",
        "type": "tool_call",
        "id": "s1",
        "args": {
            "stance": "Bullish",
            "key_evidence": [
                {"claim": "close above 50SMA",
                 "evidence": "close=178.42 vs 171.9", "source": "snapshot"}
            ],
            "key_levels": [{"label": "Resistance", "price": "179.88", "why": "session high"}],
            "risks": ["ATR rising"],
            "interpretation": "Trend intact above both averages.",
        },
    }


def _prompt():
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

    return ChatPromptTemplate.from_messages([
        ("system", "Report on {symbol}. Tools: {tool_names}."),
        MessagesPlaceholder(variable_name="messages"),
    ]).partial(symbol=SYMBOL, tool_names="get_stock_data")


def _schema():
    from tradingagents.agents.schemas import MarketAnalystReport

    return MarketAnalystReport


def _render():
    from tradingagents.agents.schemas import render_market_analyst_report

    return render_market_analyst_report


class _Tool:
    """A data tool whose executions are counted and whose result is fixed."""

    def __init__(self, name="get_stock_data", result="TOOL OUTPUT: rows"):
        self.name = name
        self.result = result
        self.calls = 0

    def invoke(self, args, config=None):
        self.calls += 1
        return self.result


class _SchemaAdapter:
    """The binding a provider would hand to the single-pass loop.

    ``bind_tools(tools + [schema])`` returns the caller's scripted transport, so
    the *schema* tool call the model emits reaches the loop as it does live: the
    loop reads ``llm.bind_tools`` and the inner transport is what is billed.
    """

    config = None

    def __init__(self, transport):
        self._transport = transport

    def bind_tools(self, tools, **kwargs):
        return self._transport


def _run_single_pass(binding, tools):
    return finalize_single_pass(
        llm=_SchemaAdapter(binding),
        structured_llm=binding,
        prompt=_prompt(),
        messages=[("human", "Analyze AAPL")],
        tools=tools,
        schema=_schema(),
        render=_render(),
        agent_name="Market Analyst",
        run_tools=run_data_tools(tools),
    )


# ---------------------------------------------------------------------------
# 1. Single-pass transport accounting
# ---------------------------------------------------------------------------


class TestSinglePassAccounting:
    def test_n_outbound_rounds_settle_as_n_invocations(self, tmp_path):
        """Two tool rounds + one schema answer = three requests, three settlements."""
        cap, ledger, run_id = _capture(tmp_path, "spn")
        binding = _ScriptedChat(script=[
            _ai(tool_calls=[_data_call("t1")], tokens=(100, 10)),
            _ai(tool_calls=[_data_call("t2")], tokens=(110, 10)),
            _ai(tool_calls=[_schema_call()], tokens=(120, 40)),
        ])
        tool = _Tool()
        with use_usage_capture(cap):
            rendered, report, _msgs = _run_single_pass(binding, [tool])
        assert rendered.strip() and report is not None
        assert binding.cursor == 3
        assert tool.calls == 2, "each executed tool round runs its tool exactly once"
        spend = ledger.read_run_spend(run_id)
        assert len(spend.events) == 3, "N outbound requests must settle as N attempts"
        assert not spend.unresolved, "no reservation may be left in flight"
        # Provider usage is preserved on every attempt (nothing is double counted,
        # nothing is re-estimated).
        assert [e.tokens_source for e in spend.events] == ["provider"] * 3
        assert sorted(e.total_tokens for e in spend.events) == [110, 120, 160]

    def test_missing_provider_usage_is_never_reported_as_zero(self, tmp_path):
        cap, ledger, run_id = _capture(tmp_path, "spzero")
        binding = _ScriptedChat(script=[_ai(tool_calls=[_schema_call()])])  # no usage
        with use_usage_capture(cap):
            _run_single_pass(binding, [])
        event = ledger.read_run_spend(run_id).events[0]
        assert event.tokens_source != "provider"
        assert event.output_tokens_source != "provider"
        assert event.total_tokens is None or event.total_tokens > 0

    def test_budget_denial_propagates_without_a_fallback_request(self, tmp_path):
        """A refusal surfaces as ``BudgetDeniedError`` with no fallback request.

        The denial is produced by the shipped admission path: the binding's own
        settlement handler refuses the attempt (here because the budget has no
        affordable call left), and the retry the loop would otherwise pay for is
        refused the same way. The run stops on the denial instead of buying a
        free-text answer, and no refused attempt settles as a real call.
        """
        cap, ledger, run_id = _capture(tmp_path, "spdeny")
        # Fail the attempt closed: a budget with no affordable call left.
        cap.debate_config = _NoBudgetLeft()

        model = _ScriptedChat(script=[_ai(tool_calls=[_schema_call()])])
        binding = _with_settlement(
            model.with_structured_output(_schema()), "market_analyst", "Market Analyst"
        )
        with use_usage_capture(cap):
            with pytest.raises(BudgetDeniedError):
                finalize_single_pass(
                    llm=_SchemaAdapter(binding),
                    structured_llm=binding,
                    prompt=_prompt(),
                    messages=[("human", "Analyze AAPL")],
                    tools=[],
                    schema=_schema(),
                    render=None,
                    agent_name="Market Analyst",
                    run_tools=run_data_tools([]),
                    accept=lambda report: "rendered",
                )
        assert model.cursor == 1, (
            "exactly one attempt is dispatched to the transport: the denial is "
            "not answered with an approved-looking fallback"
        )
        spend = ledger.read_run_spend(run_id)
        assert not spend.events, "a refused attempt must not settle as a successful call"


# ---------------------------------------------------------------------------
# 2. Settlement attachment
# ---------------------------------------------------------------------------


class _ConfiglessWrapper:
    """``with_config`` returns a wrapper that carries no settlement callback."""

    config = None

    def __init__(self):
        self.invocations = 0

    def with_config(self, **kwargs):
        class _Wrapped:
            config = {}

            def invoke(self, payload):  # pragma: no cover - must never be used
                raise AssertionError("the config-less wrapper must not be invoked")

        return _Wrapped()

    def invoke(self, payload):
        self.invocations += 1
        return {"raw": _ai("body", tokens=(30, 10)), "parsed": None, "parsing_error": None}


class TestSettlementAttachment:
    def test_with_settlement_refuses_a_wrapper_that_lacks_the_callback(self):
        binding = _ConfiglessWrapper()
        assert _with_settlement(binding, "trader", "Trader") is binding, (
            "a wrapper that does not carry the settlement handler must be refused, "
            "otherwise this attempt is silently dropped from the accounting"
        )

    def test_with_settlement_refuses_a_double_that_only_echoes_its_config(self):
        """A double whose ``config`` echoes the handler but dispatches nothing."""

        class _Echoing:
            config = None

            def with_config(self, **kwargs):
                class _Wrapped:
                    config = dict(kwargs)

                    def invoke(self, payload):  # pragma: no cover - never used
                        raise AssertionError("an echoing wrapper must not be used")

                return _Wrapped()

            def invoke(self, payload):  # pragma: no cover - never used
                return None

        binding = _Echoing()
        assert _with_settlement(binding, "trader", "Trader") is binding, (
            "an object that never dispatches the callback would drop this attempt"
        )

    def test_configless_binding_is_settled_around_the_call_exactly_once(self, tmp_path):
        cap, ledger, run_id = _capture(tmp_path, "cfgs")
        inner = _ConfiglessWrapper()
        binding = _with_settlement(inner, "trader", "Trader")
        holder: dict = {}
        with use_usage_capture(cap):
            out = _call_schema_binding(
                binding, "prompt", phase="trader", speaker="Trader", prompt_chars=10,
                # A binding with no raw envelope has no message to read usage from;
                # pass the envelope's own raw message as the (absent) hint source.
                usage_response=lambda: holder.get("out"),
                on_result=lambda result: holder.__setitem__("out", result["raw"]),
            )
        assert out["raw"].content == "body"
        assert binding.invocations == 1
        events = ledger.read_run_spend(run_id).events
        assert len(events) == 1, "the fallback instrumentation must not double count"
        assert events[0].total_tokens == 40

    def test_handler_bearing_binding_is_settled_by_its_own_handler_once(self, tmp_path):
        """The shipped path: a real binding dispatches its handler per request."""
        cap, ledger, run_id = _capture(tmp_path, "handl")
        model = _ScriptedChat(script=[_ai("body", tokens=(50, 5))])
        binding = _with_settlement(model.with_structured_output(_schema()), "trader", "Trader")
        assert binding is not None
        callbacks = (getattr(binding, "config", None) or {}).get("callbacks") or []
        handlers = [cb for cb in callbacks if isinstance(cb, UsageSettlementHandler)]
        assert len(handlers) == 1, "the shipped binding must carry its settlement handler"
        with use_usage_capture(cap):
            out = _call_schema_binding(
                binding, "prompt", phase="trader", speaker="Trader", prompt_chars=10
            )
        assert out["raw"].content == "body"
        assert model.cursor == 1, "exactly one outbound request"
        events = ledger.read_run_spend(run_id).events
        assert len(events) == 1, "the handler and the fallback must not both settle"
        assert events[0].tokens_source == "provider"
        assert events[0].total_tokens == 55
        assert not handlers[0]._pending, "every dispatched request was settled"


# ---------------------------------------------------------------------------
# 3. ``include_raw`` classification
# ---------------------------------------------------------------------------


class _StrictPlainOnly:
    """Raises for ``include_raw``; works without it (the legacy typed path)."""

    def __init__(self, exc):
        self.exc = exc
        self.bind_calls = 0

    def with_structured_output(self, schema, **kwargs):
        self.bind_calls += 1
        if "include_raw" in kwargs:
            raise self.exc
        return _ConfiglessWrapper()


class _BrokenBinding:
    def __init__(self, exc):
        self.exc = exc

    def with_structured_output(self, schema, **kwargs):
        raise self.exc


class TestIncludeRawClassification:
    @pytest.mark.parametrize("message", [
        "include_raw is not supported",
        "unexpected keyword argument 'include_raw'",
        "bad kw",
    ])
    def test_include_raw_shaped_rejection_rebinds_plain(self, message):
        llm = _StrictPlainOnly(TypeError(message))
        bound = bind_structured(llm, _schema(), "Market Analyst")
        assert bound is not None, "a rejected include_raw must keep the typed path"
        assert llm.bind_calls == 2, "one include_raw attempt plus one plain re-bind"

    def test_not_implemented_degrades_to_free_text(self):
        assert bind_structured(
            _BrokenBinding(NotImplementedError("nope")), _schema(), "Market Analyst"
        ) is None

    @pytest.mark.parametrize("message", [
        "unexpected keyword argument 'schema'",
        "missing 1 required positional argument: 'method'",
    ])
    def test_genuine_binding_defect_propagates(self, message):
        with pytest.raises(TypeError):
            bind_structured(
                _BrokenBinding(TypeError(message)), _schema(), "Market Analyst"
            )


# ---------------------------------------------------------------------------
# 4. Estimate-only attempts
# ---------------------------------------------------------------------------


class TestEstimateAccounting:
    def test_estimate_kind_counts_as_success_and_as_estimate(self):
        from tradingagents.observability import (
            RunMetricsCollector,
            record_structured_attempt,
            run_scoped,
        )

        collector = RunMetricsCollector()
        # Buckets are keyed by agent id; no agent scope is open here, so the
        # events land in the run's ``unattributed`` bucket (which the attribution
        # audit is designed to surface, not to hide).
        with run_scoped(collector):
            record_structured_attempt("Market Analyst", kind="estimate")

        # Both the full aggregate and the CLI's lightweight summary must agree.
        stats = collector.build_telemetry()
        bucket = stats["agents"][AGENT_UNATTRIBUTED]
        assert bucket["structured_successes"] == 1
        assert bucket["structured_estimate"] == 1
        assert bucket["structured_attempts"] == 1
        assert bucket["structured_fallbacks"] == 0
        assert stats["run_totals"]["structured_successes"] == 1

        from cli.stats_handler import StatsCallbackHandler

        handler = StatsCallbackHandler()
        handler._collector = collector
        summary = handler._observability_summary()
        assert summary["structured_estimate"] == 1
        assert summary["agents"][AGENT_UNATTRIBUTED]["structured_estimate"] == 1

        kinds = [ev.kind for ev in collector.structured_events]
        assert kinds == ["estimate"]
        assert "unsupported" not in kinds


# ---------------------------------------------------------------------------
# 5. GraphSetup compatibility
# ---------------------------------------------------------------------------


class TestGraphSetupCompatibility:
    def test_accepts_release_kwargs_and_feature_config(self):
        from tradingagents.graph.setup import GraphSetup

        params = inspect.signature(GraphSetup.__init__).parameters
        for name in ("quick_thinking_llm", "deep_thinking_llm", "tool_nodes",
                     "conditional_logic", "data_quality_gate_factory",
                     "debate_termination_config", "debate_evaluator_factory"):
            assert name in params, f"release keyword {name!r} must stay accepted"
        assert "config" in params, "the feature's config= must stay accepted"

    def test_keeps_positional_call_compatibility(self):
        from tradingagents.graph.setup import GraphSetup

        positional = [
            p for p in list(inspect.signature(GraphSetup.__init__).parameters.values())[1:]
            if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        ]
        assert [p.name for p in positional][:5] == [
            "quick_thinking_llm", "deep_thinking_llm", "tool_nodes",
            "conditional_logic", "data_quality_gate_factory",
        ], "an existing positional call must keep binding to the same parameters"

    def test_evidence_wrapper_composes_around_the_analyst(self):
        from langchain_core.messages import AIMessage

        from tradingagents.agents.analysts.market_analyst import create_market_analyst
        from tradingagents.graph.evidence_tool_node import EvidenceCapturingAnalystNode

        def _body():
            return AIMessage(content="## Market Report\nNo structured data.")

        class _LLM(BaseChatModel):
            # A real chat model: the analyst chains ``prompt | llm.bind_tools(...)``,
            # which only accepts another Runnable.
            @property
            def _llm_type(self):
                return "scripted-merge-analyst"

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return ChatResult(generations=[ChatGeneration(message=_body())])

            def with_structured_output(self, schema, **kwargs):
                return _ConfiglessWrapper()

            def bind_tools(self, tools, **kwargs):
                # ``BaseChatModel.bind_tools`` raises NotImplementedError; this
                # double has no tool protocol, so it just answers with prose.
                return self

        node = create_market_analyst(_LLM())
        wrapped = EvidenceCapturingAnalystNode(node, name="Market Analyst")
        assert wrapped is not node, "the evidence wrapper must stay in the composed chain"
        state = {
            "messages": [("human", SYMBOL)],
            "company_of_interest": SYMBOL,
            "trade_date": TARGET,
            "asset_type": "stock",
        }
        with use_collector(SYMBOL, TARGET):
            out = wrapped(state, {}, None)
            assert get_active_collector() is not None
        assert out["market_report"].strip(), "the inner analyst still produces a report"


# ---------------------------------------------------------------------------
# 6. Analyst factories
# ---------------------------------------------------------------------------


class TestAnalystFactories:
    def test_create_news_analyst_accepts_the_merged_switch_set(self):
        from tradingagents.agents.analysts.news_analyst import create_news_analyst

        params = inspect.signature(create_news_analyst).parameters
        for name in ("batch_macro", "structured", "single_pass"):
            assert name in params, f"create_news_analyst must accept {name!r}"

    def test_every_analyst_factory_call_site_passes_supported_arguments(self):
        from tradingagents.agents.analysts import (
            fundamentals_analyst,
            market_analyst,
            news_analyst,
        )

        package_root = Path(market_analyst.__file__).resolve().parents[3]
        factories = {
            "create_market_analyst": inspect.signature(market_analyst.create_market_analyst),
            "create_fundamentals_analyst": inspect.signature(
                fundamentals_analyst.create_fundamentals_analyst
            ),
            "create_news_analyst": inspect.signature(news_analyst.create_news_analyst),
        }
        checked = 0
        for path in sorted(package_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                signature = factories.get(name)
                if signature is None:
                    continue
                checked += 1
                params = signature.parameters
                for keyword in node.keywords:
                    if keyword.arg is None:
                        continue  # **splat
                    assert keyword.arg in params, (
                        f"{path.name}: {name}(..., {keyword.arg}=...) is not a parameter"
                    )
                positional = [
                    p for p in params.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
                assert len(node.args) <= len(positional), (
                    f"{path.name}: {name} called with {len(node.args)} positional arguments"
                )
        assert checked >= 3, "the call-site scan must actually find the factory calls"


# ---------------------------------------------------------------------------
# 7. News evidence capture (Finnhub)
# ---------------------------------------------------------------------------


class TestFinnhubCapture:
    def test_missing_credential_records_a_failed_attempt_and_reraises(self, monkeypatch):
        from tradingagents.dataflows.errors import VendorNotConfiguredError

        def _no_key():
            raise VendorNotConfiguredError("Finnhub API key is not configured")

        monkeypatch.setattr(finnhub_news, "get_api_key", _no_key)
        with use_collector(SYMBOL, TARGET) as collector:
            with pytest.raises(VendorNotConfiguredError):
                finnhub_news.fetch_news_finnhub(SYMBOL, "2026-05-06", TARGET)
            attempts = collector.state_delta()["data_quality_source_attempt_envelopes"]
        assert len(attempts) == 1, "a provider that was asked and failed is an attempt"
        assert attempts[0]["attempt"]["source"] == "finnhub_news"
        assert attempts[0]["attempt"]["result_status"] == "failed"
        assert attempts[0]["attempt"]["error_type"] == "AUTH_MISSING"

    def test_provider_failure_records_a_failed_attempt_and_reraises(self, monkeypatch):
        from tradingagents.dataflows.errors import VendorRateLimitError

        monkeypatch.setattr(finnhub_news, "get_api_key", lambda: "placeholder")
        monkeypatch.setattr(finnhub_news, "_request", lambda url: (429, "", ""))
        monkeypatch.setattr(finnhub_news.time, "sleep", lambda *_: None)
        with use_collector(SYMBOL, TARGET) as collector:
            with pytest.raises(VendorRateLimitError):
                finnhub_news.fetch_news_finnhub(SYMBOL, "2026-05-06", TARGET)
            attempts = collector.state_delta()["data_quality_source_attempt_envelopes"]
        assert len(attempts) == 1
        assert attempts[0]["attempt"]["result_status"] == "failed"
        assert attempts[0]["attempt"]["error_type"] == "RATE_LIMITED"

    def test_empty_window_is_recorded_as_an_empty_attempt(self, monkeypatch):
        monkeypatch.setattr(finnhub_news, "get_api_key", lambda: "placeholder")
        monkeypatch.setattr(finnhub_news, "_request", lambda url: (200, "[]", ""))
        with use_collector(SYMBOL, TARGET) as collector:
            outcome = finnhub_news.fetch_news_finnhub(SYMBOL, "2026-05-06", TARGET)
            attempts = collector.state_delta()["data_quality_source_attempt_envelopes"]
        assert outcome.status is finnhub_news.NewsStatus.EMPTY_VALID
        assert len(attempts) == 1
        assert attempts[0]["attempt"]["result_status"] == "empty"

    def test_capture_is_a_noop_outside_a_run(self, monkeypatch):
        monkeypatch.setattr(finnhub_news, "get_api_key", lambda: "placeholder")
        monkeypatch.setattr(finnhub_news, "_request", lambda url: (200, "[]", ""))
        assert get_active_collector() is None
        outcome = finnhub_news.fetch_news_finnhub(SYMBOL, "2026-05-06", TARGET)
        assert outcome.status is finnhub_news.NewsStatus.EMPTY_VALID


# ---------------------------------------------------------------------------
# 8. Settlement response shapes
# ---------------------------------------------------------------------------


class TestSettlementResponseShape:
    def test_bare_chat_result_yields_the_provider_message(self):
        """A ``ChatResult`` (not an ``LLMResult``) must still expose its message.

        A settlement handler receives whatever the binding's callback manager
        passes to ``on_llm_end``; a binding that completes its own request hands
        over a bare ``ChatResult``, whose ``generations`` is one list of
        generation objects rather than a list of generation lists. Reading only
        the nested shape silently lost the provider's usage and silently billed
        the attempt as a character estimate.
        """
        from langchain_core.outputs import LLMResult

        from tradingagents.agents.utils.structured import _raw_message_from_response

        message = _ai("body", tokens=(50, 5))
        assert _raw_message_from_response(ChatResult(
            generations=[ChatGeneration(message=message)])) is message
        # The nested ``LLMResult`` shape keeps working.
        assert _raw_message_from_response(LLMResult(
            generations=[[ChatGeneration(message=message)]])) is message
        # A result with nothing usable is ``None``, never a fabricated message.
        assert _raw_message_from_response(ChatResult(generations=[])) is None
        assert _raw_message_from_response(LLMResult(generations=[[]])) is None
        assert _raw_message_from_response(object()) is None
