# TradingAgents/graph/trading_graph.py

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yfinance as yf
from langgraph.prebuilt import ToolNode

# Import the abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_stock_data,
    get_verified_market_snapshot,
    resolve_instrument_identity,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.agents.utils.output_guard import is_blocked_run
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import get_current_date, safe_ticker_component
from tradingagents.debate.config import resolve_debate_termination_config
from tradingagents.debate.usage_capture import (
    UsageCapture,
    use_usage_capture,
)
from tradingagents.debate.usage_ledger import (
    LedgerError,
    UsageLedger,
    ledger_path_for_results_dir,
    new_run_id,
    policy_signature,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.evidence.ingest import use_collector
from tradingagents.llm_clients import create_llm_client
from tradingagents.reporting import write_report_tree

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .setup import GraphSetup
from .signal_processing import SignalProcessor

logger = logging.getLogger(__name__)


def _resolve_usage_run_identity(results_dir, company_name, trade_date, prior_state):
    """Module-level ADR-009 execution identity resolver.

    Kept module-level (not only a method) so it works even when the graph class is
    exercised via a lightweight test double: a RESUME reuses the persisted
    ``run_id`` (same execution keeps its own spend); a genuinely fresh run mints a
    new identity (never inheriting a prior finished run's spend). Returns
    ``(run_id, ledger_path)``.
    """
    ledger_path = ledger_path_for_results_dir(results_dir, company_name, str(trade_date))
    if isinstance(prior_state, dict):
        prior_run_id = prior_state.get("run_id")
        if isinstance(prior_run_id, str) and prior_run_id:
            return prior_run_id, prior_state.get("usage_ledger_path") or ledger_path
    return new_run_id(company_name, str(trade_date)), ledger_path


def _open_usage_ledger(ledger_path, *, strict_resume: bool = False):
    """Module-level ADR-009 ledger opener (fresh create vs strict resume).

    A FRESH run opens/creates the ledger. A RESUME opens the EXISTING ledger
    strictly: a missing file / absent run row raises and yields ``None`` so the
    caller keeps accounting unreadable (fail closed) rather than initializing a
    replacement and resetting spend to zero.
    """
    if not ledger_path:
        return None
    try:
        if strict_resume:
            from tradingagents.debate.usage_ledger import open_ledger_strict

            return open_ledger_strict(ledger_path)
        return UsageLedger(ledger_path)
    except (LedgerError, OSError) as exc:
        logger.warning(
            "Could not open usage ledger (%s); accounting unreadable", type(exc).__name__
        )
        return None


def _validate_trade_date(trade_date) -> str:
    """The run date as a canonical ``YYYY-MM-DD`` string no later than today."""
    value = str(trade_date)
    try:
        canonical = datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
    except ValueError:
        canonical = False
    if not canonical:
        raise ValueError(f"trade_date must be a date in YYYY-MM-DD format, got {trade_date!r}")
    if value > get_current_date():
        raise ValueError(f"trade_date cannot be in the future: {value}")
    return value


def _coerce_max_retries(value):
    """Validate an ``llm_max_retries`` value to a non-negative int.

    Accepts an int or a numeric string (env vars arrive as strings). Rejects
    booleans and negatives loudly so a misconfiguration fails at startup rather
    than silently disabling retries.
    """
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries must be an integer, got {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries must be >= 0, got {n}")
    return n


def _coerce_max_tokens(value):
    """Validate a ``max_tokens`` value to a positive int (env vars are strings)."""
    if isinstance(value, bool):
        raise ValueError(f"max_tokens must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max_tokens must be an integer, got {value!r}") from exc
    if n <= 0:
        raise ValueError(f"max_tokens must be > 0, got {n}")
    return n


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            debate_termination_config=resolve_debate_termination_config(self.config),
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Graph-shape-affecting run choices, kept for the checkpoint signature.
        self.selected_analysts = tuple(selected_analysts)

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None
        self._resuming = False

    def _get_provider_kwargs(self) -> dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        # Sampling temperature is cross-provider: forward it whenever set.
        # float() here so a value coming from a TRADINGAGENTS_TEMPERATURE env
        # string ("0.2") works the same as a programmatic float.
        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        # SDK retry budget is cross-provider. Forward it only when explicitly set
        # so each provider keeps its own default (usually 2) otherwise (#1091).
        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None and max_retries != "":
            kwargs["max_retries"] = _coerce_max_retries(max_retries)

        # Output-token cap is cross-provider, but Gemini names it
        # ``max_output_tokens``; forward under the right key when set (#1204).
        max_tokens = self.config.get("max_tokens")
        if max_tokens is not None and max_tokens != "":
            key = "max_output_tokens" if provider == "google" else "max_tokens"
            kwargs[key] = _coerce_max_tokens(max_tokens)

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                    # Deterministic verification snapshot (bound to the analyst
                    # LLM and required by its prompt; must be executable here or
                    # the call fails and the model reports it "unavailable").
                    get_verified_market_snapshot,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                    get_macro_indicators,
                    get_prediction_markets,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def _resolve_benchmark(self, ticker: str) -> str:
        """Pick the benchmark ticker for alpha calculation against ``ticker``.

        ``config["benchmark_ticker"]`` overrides everything when set; otherwise
        the suffix map matches the ticker's exchange suffix (e.g. ``.T`` for
        Tokyo). US-listed tickers without a dotted suffix fall through to the
        empty-suffix entry (SPY by default). Unrecognised suffixes (including
        US tickers with dots like ``BRK.B``) also fall back to the empty-suffix
        entry, which is the right default because the alpha calculation works
        in USD.
        """
        from tradingagents.dataflows.symbol_utils import normalize_symbol

        explicit = self.config.get("benchmark_ticker")
        if explicit:
            # Same alias mapping as the analyzed ticker; an unmapped alias finds
            # no prices, and the decision would stay pending for good.
            return normalize_symbol(explicit)
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = normalize_symbol(ticker)
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return benchmark
        return benchmark_map.get("", "SPY")

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> tuple[float | None, float | None, int | None, str | None]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        holding_days, resolution_date)`` — where ``resolution_date`` is the date
        of the last price bar used, i.e. when the outcome became known (#1251) —
        or ``(None, None, None, None)`` when the outcome cannot be settled yet:
        the full holding window has not traded (#1169), or the symbol is delisted
        or unreachable.
        """
        from tradingagents.dataflows.symbol_utils import normalize_symbol

        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            # holding_days counts trading days, so ask for the calendar span they
            # occupy (about 7 for every 5) plus a week for holidays.
            end = start + timedelta(days=round(holding_days * 7 / 5) + 7)
            end_str = end.strftime("%Y-%m-%d")

            # Normalize so the realized-return lookup hits the same instrument
            # the analysis priced (e.g. XAUUSD -> GC=F) (#984). The benchmark is
            # already a canonical Yahoo symbol from ``_resolve_benchmark``.
            stock = yf.Ticker(normalize_symbol(ticker)).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            # Require the full holding window in both series. A rerun before it
            # has traded leaves the entry pending to retry next run, rather than
            # settling on a premature partial return (#1169).
            if len(stock) <= holding_days or len(bench) <= holding_days:
                return None, None, None, None

            raw = float(
                (stock["Close"].iloc[holding_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            bench_ret = float(
                (bench["Close"].iloc[holding_days] - bench["Close"].iloc[0])
                / bench["Close"].iloc[0]
            )
            alpha = raw - bench_ret
            # The date of the last price bar used is when this outcome became
            # known — the point-in-time cutoff for injecting the lesson (#1251).
            resolution_date = stock.index[holding_days].strftime("%Y-%m-%d")
            return raw, alpha, holding_days, resolution_date
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        benchmark = self._resolve_benchmark(ticker)
        updates = []
        for entry in pending:
            raw, alpha, days, resolution_date = self._fetch_returns(
                ticker, entry["date"], self.config.get("holding_period_days", 5),
                benchmark=benchmark,
            )
            if raw is None:
                continue  # price not available yet — try again next run
            try:
                reflection = self.reflector.reflect_on_final_decision(
                    final_decision=entry.get("decision", ""),
                    raw_return=raw,
                    alpha_return=alpha,
                    benchmark_name=benchmark,
                    holding_days=days,
                )
            except Exception as exc:
                # Reflection calls a provider, and this runs on the way into a
                # new run: a transient failure leaves the entry pending for the
                # next one rather than stopping the analysis that was asked for.
                logger.warning("Reflection failed for %s on %s: %s", ticker, entry["date"], exc)
                continue
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
                "resolution_date": resolution_date,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock",
                                   curr_date: str | None = None) -> str:
        """Resolve ticker identity once and return the full instrument context.

        Deterministic yfinance lookup (cached, fail-open) injected into a
        context string so every agent anchors to the real company instead of
        hallucinating one from the price chart (#814). Both the propagate()
        path and the CLI call this so the resolved identity reaches the whole
        graph regardless of entry point.
        """
        identity = resolve_instrument_identity(ticker)
        return build_instrument_context(ticker, asset_type, identity, curr_date)

    def _memory_as_of(self, trade_date) -> str | None:
        """Point-in-time cutoff for past-context lessons (#1251).

        A historical/backtest run (trade date before today) filters lessons to
        those already resolved by the trade date. A current-date run returns
        None, disabling the filter so live behavior and pre-migration entries
        (which have no stored resolution date) are unaffected.
        """
        td = str(trade_date)
        return td if td < datetime.now().strftime("%Y-%m-%d") else None

    def _run_signature(self, asset_type: str, portfolio=None) -> str:
        """Graph-shape inputs that must invalidate a checkpoint if changed.

        Keyed into the checkpoint thread ID so a resume under a different analyst
        selection, debate/risk depth, or asset mode starts fresh instead of
        silently continuing the previous graph (#1089).
        """
        return "|".join([
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={self.config['max_debate_rounds']}",
            f"risk={self.config['max_risk_discuss_rounds']}",
            f"asset={asset_type}",
            # None, an empty book and a changed book are three different runs.
            f"portfolio={portfolio.fingerprint() if portfolio is not None else 'none'}",
        ])

    def propagate(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.

        Returns ``(final_state, signal)`` where ``signal`` is one of the 5-tier
        ratings (Buy / Overweight / Hold / Underweight / Sell) or ``"REVIEW"``
        when the decision had no parseable rating (#1170); guard with
        ``tradingagents.agents.utils.rating.is_review`` before mapping it to the
        PortfolioRating enum.
        """
        trade_date = _validate_trade_date(trade_date)
        self.ticker = company_name

        with self.checkpoint_scope(company_name, trade_date, asset_type, portfolio) as thread_id_value:
            return self._run_graph(
                company_name, trade_date, asset_type=asset_type,
                checkpoint_thread_id=thread_id_value, portfolio=portfolio,
            )

    def begin_checkpoint(self, company_name, trade_date, asset_type: str = "stock", portfolio=None) -> str | None:
        """Recompile the graph with a per-ticker checkpointer and return the
        ``thread_id`` to inject into the stream/invoke ``config`` (or ``None``
        when checkpointing is disabled).

        Pair every call with :meth:`end_checkpoint` in a ``finally``. Both
        ``propagate`` (via :meth:`checkpoint_scope`) and the CLI stream path use
        this so ``--checkpoint`` actually resumes (#1249); previously the setup
        lived only inside ``propagate`` and the CLI streamed the checkpointer-less
        graph, making the flag a no-op.
        """
        self._resuming = False
        if not self.config.get("checkpoint_enabled"):
            return None
        signature = self._run_signature(asset_type, portfolio)
        self._checkpointer_ctx = get_checkpointer(self.config["data_cache_dir"], company_name)
        saver = self._checkpointer_ctx.__enter__()
        self.graph = self.workflow.compile(checkpointer=saver)

        step = checkpoint_step(
            self.config["data_cache_dir"], company_name, str(trade_date), signature
        )
        self._resuming = step is not None
        if step is not None:
            logger.info("Resuming from step %d for %s on %s", step, company_name, trade_date)
        else:
            logger.info("Starting fresh for %s on %s", company_name, trade_date)
        return thread_id(company_name, str(trade_date), signature)

    def checkpoint_input(self, init_state):
        """The value to stream/invoke: ``None`` to resume an existing checkpoint,
        else the initial state for a fresh run.

        LangGraph resumes an interrupted thread when invoked with ``None``;
        re-passing the initial state instead appends it through the message
        reducer, duplicating messages in the resumed state (#1249).
        """
        return None if self._resuming else init_state

    def _usage_run_identity(self, company_name, trade_date, prior_state):
        """Resolve the ADR-009 execution identity for this run (fresh vs resume).

        Delegates to the module-level resolver so the CLI and the graph share one
        implementation. A RESUME reuses the persisted ``run_id``; a genuinely
        fresh run mints a new identity. Returns ``(run_id, ledger_path)``.
        """
        return _resolve_usage_run_identity(
            self.config.get("results_dir"), company_name, trade_date, prior_state
        )

    def _sanitize_confidence_on_resume(self, args: dict[str, Any], prior_state: dict[str, Any]) -> None:
        """Cap prior persisted confidence on a degraded resume, FAIL CLOSED.

        Builds a bounded state delta that caps every persisted debate turn's
        numeric confidence and readable content, every stance snapshot's
        confidence, the readable analyst reports / debate histories / risk
        histories and the stored plans/decisions, then applies it with
        ``graph.update_state`` so the NEXT node reads the sanitized values.

        FAIL CLOSED: if building or applying the sanitized delta raises while the
        verdict is degraded, the exception is RE-RAISED so the caller refuses to
        run the resumed graph (deterministic safe outcome) — an overconfident
        legacy checkpoint is never silently continued. A non-degraded verdict is
        untouched. The operation is idempotent (capped values carry no over-cap
        token) and never duplicates audit entries.
        """
        from tradingagents.debate.confidence_policy import current_trusted_verdict

        verdict = current_trusted_verdict(prior_state)
        if verdict != "degraded":
            return
        delta = self._build_confidence_sanitize_delta(prior_state)
        if not delta:
            return
        # Raises (and MUST propagate) if update_state fails: the resumed graph
        # must not run against an unsanitized overconfident checkpoint.
        self.graph.update_state(args.get("config"), delta)

    @staticmethod
    def _build_confidence_sanitize_delta(prior_state: dict[str, Any]) -> dict[str, Any]:
        """The state delta that caps persisted confidence on a degraded resume.

        Preserves per-boundary / per-turn raw+effective+reason provenance (via the
        confidence policy sanitizers), quarantines invalid legacy numerics, and
        sanitizes the analyst reports + debate/risk histories that downstream nodes
        read into their prompts. Audit entries are merged (deduped by identity) so a
        repeated safe resume does not duplicate them.
        """
        from tradingagents.debate.confidence_policy import (
            boundary_id,
            merge_audit,
            sanitize_persisted_numeric,
            sanitize_persisted_text,
        )

        delta: dict[str, Any] = {}
        new_audit: list[dict[str, Any]] = []

        debate = prior_state.get("investment_debate_state")
        if isinstance(debate, dict):
            new_debate = dict(debate)
            turns = debate.get("turns")
            if isinstance(turns, list):
                capped_turns = []
                for index, turn in enumerate(turns):
                    if isinstance(turn, dict):
                        new_turn = dict(turn)
                        speaker = str(new_turn.get("speaker", "") or "debate")
                        value, entry = sanitize_persisted_numeric(
                            new_turn.get("confidence"),
                            source=speaker,
                            boundary=boundary_id("resume_turn_numeric", speaker, index),
                        )
                        new_turn["confidence"] = value
                        if entry is not None:
                            new_audit.append(entry)
                        if isinstance(new_turn.get("content"), str):
                            text, entries = sanitize_persisted_text(
                                new_turn["content"],
                                source=speaker,
                                boundary=boundary_id("resume_turn_text", speaker, index),
                            )
                            new_turn["content"] = text
                            new_audit.extend(entries)
                        capped_turns.append(new_turn)
                    else:
                        capped_turns.append(turn)
                new_debate["turns"] = capped_turns
            stances = debate.get("stances")
            if isinstance(stances, dict):
                new_stances = {}
                for speaker, snap in stances.items():
                    if isinstance(snap, dict):
                        new_snap = dict(snap)
                        value, entry = sanitize_persisted_numeric(
                            new_snap.get("confidence"),
                            source=str(speaker),
                            boundary=boundary_id("resume_stance", str(speaker)),
                        )
                        new_snap["confidence"] = value
                        if entry is not None:
                            new_audit.append(entry)
                        new_stances[speaker] = new_snap
                    else:
                        new_stances[speaker] = snap
                new_debate["stances"] = new_stances
            for hist_key in ("history", "bull_history", "bear_history", "current_response", "judge_decision"):
                if isinstance(new_debate.get(hist_key), str):
                    text, entries = sanitize_persisted_text(
                        new_debate[hist_key],
                        source="debate",
                        boundary=boundary_id("resume_debate_history", hist_key),
                    )
                    new_debate[hist_key] = text
                    new_audit.extend(entries)
            delta["investment_debate_state"] = new_debate

        # Analyst reports are read into downstream prompts (e.g. trader).
        for report_key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
            if isinstance(prior_state.get(report_key), str):
                text, entries = sanitize_persisted_text(
                    prior_state[report_key],
                    source="report",
                    boundary=boundary_id("resume_analyst_report", report_key),
                )
                delta[report_key] = text
                new_audit.extend(entries)

        for text_key in ("investment_plan", "trader_investment_plan", "final_trade_decision"):
            if isinstance(prior_state.get(text_key), str):
                text, entries = sanitize_persisted_text(
                    prior_state[text_key],
                    source="plan",
                    boundary=boundary_id("resume_plan", text_key),
                )
                delta[text_key] = text
                new_audit.extend(entries)

        risk = prior_state.get("risk_debate_state")
        if isinstance(risk, dict):
            new_risk = dict(risk)
            for hist_key in (
                "history", "aggressive_history", "conservative_history",
                "neutral_history", "current_aggressive_response",
                "current_conservative_response", "current_neutral_response",
                "judge_decision",
            ):
                if isinstance(new_risk.get(hist_key), str):
                    text, entries = sanitize_persisted_text(
                        new_risk[hist_key],
                        source="risk",
                        boundary=boundary_id("resume_risk_history", hist_key),
                    )
                    new_risk[hist_key] = text
                    new_audit.extend(entries)
            delta["risk_debate_state"] = new_risk

        if new_audit:
            delta["confidence_cap_audit"] = merge_audit(
                prior_state.get("confidence_cap_audit"), new_audit
            )
        return delta

    def _read_checkpoint_state(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """The latest saved graph state for the current checkpoint thread, or None.

        Used to re-seed the evidence collector on a resume so a new tool call
        appends after the already-captured evidence instead of overwriting an
        index-0 attempt/record. Never raises: a read failure yields ``None`` and
        the collector simply starts empty (capture is still persisted going
        forward).
        """
        try:
            snapshot = self.graph.get_state(args.get("config"))
            values = getattr(snapshot, "values", None)
            return dict(values) if isinstance(values, dict) else None
        except Exception as exc:  # noqa: BLE001 — a read miss must not block resume
            logger.warning("Could not read checkpoint state to seed collector: %s", exc)
            return None

    def end_checkpoint(self):
        """Restore the plain uncheckpointed graph after a checkpointed run."""
        if self._checkpointer_ctx is not None:
            self._checkpointer_ctx.__exit__(None, None, None)
            self._checkpointer_ctx = None
            self.graph = self.workflow.compile()
        self._resuming = False

    @contextmanager
    def checkpoint_scope(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Context-manager form of begin/end_checkpoint for the propagate path."""
        try:
            yield self.begin_checkpoint(company_name, trade_date, asset_type, portfolio)
        finally:
            self.end_checkpoint()

    def clear_checkpoint_on_success(self, company_name, trade_date, asset_type: str = "stock", portfolio=None):
        """Drop a completed run's checkpoint so a later run starts fresh (#1249)."""
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date),
                self._run_signature(asset_type, portfolio),
            )

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        """Write the markdown report tree for a completed run, like the CLI does.

        Programmatic callers get the same on-disk reports the CLI produces. Pass
        an explicit ``save_path`` or let it default under ``results_dir``.
        """
        if save_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = (
                Path(self.config["results_dir"])
                / "reports"
                / f"{safe_ticker_component(ticker)}_{stamp}"
            )
        return write_report_tree(final_state, ticker, save_path)

    def create_run_state(self, company_name, trade_date, asset_type: str = "stock", portfolio=None,
                         run_id: str | None = None, usage_ledger_path: str | None = None):
        """Build a run's initial state; propagate() and the CLI both start here.

        Settles this ticker's pending decisions first, then injects the lessons
        known by the trade date for the Portfolio Manager (#1251) and the
        resolved instrument identity for every agent (#814). An entry point that
        assembled the state itself would skip the decision log.

        ``run_id``/``usage_ledger_path`` (ADR-009) carry the execution identity so
        the usage capture scopes spend to exactly this execution.
        """
        self._resolve_pending_entries(company_name)
        return self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=self.memory_log.get_past_context(
                company_name, as_of=self._memory_as_of(trade_date)
            ),
            instrument_context=self.resolve_instrument_context(company_name, asset_type, trade_date),
            portfolio_context=portfolio.render(company_name) if portfolio is not None else "",
            results_dir=self.config.get("results_dir", "") or "",
            run_id=run_id,
            usage_ledger_path=usage_ledger_path,
        )

    def settle_pending(self, company_name):
        """Settle this ticker's decisions whose holding window has now traded.

        A run settles the ticker's earlier decisions on its way in, so the most
        recent one stays pending until the next run for that ticker. A caller
        that is done analyzing a ticker (a backtest sweep, a scheduled job) calls
        this to settle it now.
        """
        self._resolve_pending_entries(company_name)

    @staticmethod
    def _is_blocked_state(final_state) -> bool:
        """True when the structured gate state proves the run was blocked.

        Reuses the output guard's fail-closed reader so the memory log, the final
        signal, and the report can never disagree about a blocked run. A legacy
        state that carries no gate fields at all (e.g. a minimal unit-test dict)
        is not a blocked run: it falls back to parsing the decision text, which
        preserves existing behavior outside the gate-aware pipeline.
        """
        if not isinstance(final_state, dict):
            return False
        if "data_quality_gate_decision" not in final_state and (
            "data_quality_verdict" not in final_state
        ):
            return False
        return is_blocked_run(final_state)

    def record_decision(self, company_name, trade_date, final_state):
        """Log a finished run's decision for reflection on the next same-ticker run."""
        decision = final_state.get("final_trade_decision")
        if not decision:
            logger.warning("No final decision for %s on %s; nothing logged", company_name, trade_date)
            return
        # ADR-010: enforce at the memory boundary too — a rejected exact fact must
        # never be persisted as a trusted decision even if it slipped through.
        from tradingagents.agents.utils.output_guard import enforce_trusted_boundary

        decision = enforce_trusted_boundary(decision, final_state)
        # ADR-011: the memory decision must carry the trusted EFFECTIVE confidence
        # (a degraded run's raw over-cap confidence is never persisted).
        from tradingagents.debate.confidence_policy import cap_agent_text

        decision, _cap_entries = cap_agent_text(
            decision, final_state,
            source="memory", boundary="memory_decision",
        )
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=decision,
            blocked=self._is_blocked_state(final_state),
        )

    def _open_usage_ledger(self, ledger_path: str | None, *, strict_resume: bool = False) -> UsageLedger | None:
        """Open the durable usage ledger (or ``None`` when no path is configured).

        Delegates to the module-level opener. A resume opens strictly (a missing
        file is not recreated); an open failure is surfaced later as
        ``accounting_unreadable`` so the pre-call guard fails closed for OPTIONAL
        debate calls while the run completes its safe path.
        """
        return _open_usage_ledger(ledger_path, strict_resume=strict_resume)

    def _run_graph(self, company_name, trade_date, asset_type: str = "stock",
                   checkpoint_thread_id: str | None = None, portfolio=None):
        """Execute the graph and write the resulting state to disk and memory log."""
        args = self.propagator.get_graph_args()

        # Inject the checkpoint thread_id (from checkpoint_scope) so the same
        # ticker+date+graph-shape resumes; a different one starts fresh (#1089).
        if checkpoint_thread_id is not None:
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = checkpoint_thread_id

        # ADR-009: resolve the real execution identity (resume keeps its own;
        # a fresh run mints a new one, never inheriting a prior finished run).
        prior_state = (
            self._read_checkpoint_state(args)
            if self._resuming
            else None
        )
        run_id, ledger_path = _resolve_usage_run_identity(
            self.config.get("results_dir"), company_name, trade_date, prior_state
        )

        init_agent_state = self.create_run_state(
            company_name, trade_date, asset_type, portfolio,
            run_id=run_id, usage_ledger_path=ledger_path,
        )

        # None resumes an existing checkpoint; init_agent_state starts fresh (#1249).
        graph_input = self.checkpoint_input(init_agent_state)

        # ADR-011 resume defense: sanitize any PRIOR persisted debate turns /
        # stances / history / readable plans on a degraded run BEFORE the next
        # model prompt runs, so a resumed run cannot put a raw over-cap confidence
        # back in front of a model even if an older checkpoint stored one. This
        # rewrites the checkpoint in place (idempotent; capped values carry no
        # over-cap token so a second resume is a no-op).
        if self._resuming and prior_state is not None:
            self._sanitize_confidence_on_resume(args, prior_state)

        # ADR-009: open the durable ledger and register the run identity (idempotent
        # on resume) BEFORE the graph runs, so reservations precede every call.
        ledger = _open_usage_ledger(
            ledger_path, strict_resume=bool(getattr(self, "_resuming", False))
        )
        if ledger is not None:
            try:
                ledger.begin_run(
                    run_id,
                    policy_signature=policy_signature(
                        debate_config=resolve_debate_termination_config(self.config)
                    ),
                    # On resume the run row MUST already exist: never mint/register
                    # a new run under an existing checkpoint identity.
                    require_existing=bool(getattr(self, "_resuming", False)),
                )
            except LedgerError as exc:
                logger.warning("Usage ledger run registration failed (%s); unreadable", type(exc).__name__)
                ledger = None
        capture = UsageCapture(run_id=run_id, ledger=ledger)
        # The capture needs the debate config so a reservation stores the same
        # estimated next-call cost the pre-call guard uses.
        capture.debate_config = resolve_debate_termination_config(self.config)
        # A CONFIGURED durable ledger path that could not be opened/registered (a
        # fresh OR resumed run) must fail closed: mark accounting unreadable so
        # further OPTIONAL calls are refused rather than silently becoming a
        # memory-only run that spends without a durable reservation. An INTENTIONAL
        # no-path run (``ledger_path`` falsy) stays the legitimate legacy memory-only
        # mode with no hidden global limit.
        if ledger_path and ledger is None:
            capture.accounting_unreadable = True

        # ADR-008: bind a request/run-scoped evidence collector for exactly this
        # run so vendor dataflows capture structured optional evidence the gate
        # reads. On a RESUME the collector is re-seeded from the already-saved
        # checkpoint state (prior records/attempts/tombstones/metadata), so a new
        # tool call appends a monotonic attempt/record instead of a fresh index-0
        # overwriting the saved one. The binding is scoped (ContextVar) and torn
        # down after the run, so concurrent runs cannot share records.
        collector = use_collector(company_name, str(trade_date), prior_state=prior_state)
        with collector, use_usage_capture(capture):
            if self.debug:
                trace = []
                last_printed = None
                for chunk in self.graph.stream(graph_input, **args):
                    if chunk["messages"]:
                        msg = chunk["messages"][-1]
                        # Nodes after the trader don't append to messages, so the
                        # same trailing message repeats across chunks. Print it only
                        # when it changes (#1027); the trace/state merge is unchanged.
                        signature = (type(msg).__name__, getattr(msg, "content", None))
                        if signature != last_printed:
                            msg.pretty_print()
                            last_printed = signature
                        trace.append(chunk)
                # Streamed chunks are per-node deltas. Merge them so the returned
                # state matches what graph.invoke() yields in the non-debug path.
                final_state = {}
                for chunk in trace:
                    final_state.update(chunk)
            else:
                final_state = self.graph.invoke(graph_input, **args)

        # ADR-009: reconcile whole-run usage from the durable ledger and attach it
        # for reporting (reporting only; never a budget limit). The execution
        # identity is also stamped so a downstream report can name the run.
        self._attach_whole_run_usage(final_state, capture, run_id)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        self.record_decision(company_name, trade_date, final_state)

        # Clear checkpoint on successful completion to avoid stale state.
        self.clear_checkpoint_on_success(company_name, trade_date, asset_type, portfolio)

        return final_state, self.process_signal(final_state["final_trade_decision"])

    @staticmethod
    def _attach_whole_run_usage(final_state, capture, run_id):
        """Attach ``whole_run_usage`` (reporting only) and the execution run_id."""
        from tradingagents.debate.budget import aggregate_whole_run_usage

        if not isinstance(final_state, dict):
            return
        final_state.setdefault("run_id", run_id)
        try:
            spend = capture.reconcile()
            whole = aggregate_whole_run_usage(spend.events, spend.unresolved)
        except LedgerError:
            # The durable history is unreadable, but this process may still hold
            # KNOWN actual settled events. Retain that labelled subtotal and mark
            # the unknown history, rather than losing the known calls entirely.
            known = capture.settled_events()
            whole = aggregate_whole_run_usage(known, accounting_unreadable=True)
            whole["completeness"] = "partial" if known else "unknown"
            whole["accounting_unreadable"] = True
        final_state["whole_run_usage"] = whole

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            # Reports can be in any language and this file is read by a person.
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4, ensure_ascii=False)

    def process_signal(self, full_signal, state=None):
        """Process a signal to extract the core decision.

        ``state`` is optional for backward compatibility; when omitted it falls
        back to the run's ``curr_state`` (set by ``_run_graph``). A blocked gate
        verdict forces the authoritative ``Hold`` signal even if the rendered
        decision text carries an unrecognized directional header.
        """
        resolved_state = getattr(self, "curr_state", None) if state is None else state
        return self.signal_processor.process_signal(full_signal, resolved_state)
