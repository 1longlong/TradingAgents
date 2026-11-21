"""FR-TRD-005/006, ADR-001-simulated-trading-system.md: core walk-forward adapter."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import date
from decimal import Decimal

from trading.backtest import (
    BacktestResult,
    BacktestRunner,
    DecisionProvider,
    HistoricalQuoteProvider,
    MockDecisionProvider,
    MockQuoteProvider,
    QuoteProvider,
    RealDecisionProvider,
    WeekdayCalendar,
)
from trading.clock import SimulationClock
from trading.models import DecisionAction, EventType
from trading.runtime import RuntimeConfig, build_runtime
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.graph.trading_graph import _validate_trade_date
from tradingagents_web.api.config import effective_defaults
from tradingagents_web.errors import run_failure
from tradingagents_web.runtime.analysis_graph import WebAnalysisGraph
from tradingagents_web.runtime.simulation import SimulationError, public, write_json


class SimulationJobs:
    def __init__(self, service):
        self.service = service
        self.running: dict[str, dict] = {}

    def validate(self, body):
        start, end = (
            date.fromisoformat(_validate_trade_date(body.start)),
            date.fromisoformat(_validate_trade_date(body.end)),
        )
        if end < start or (end - start).days > 365:
            raise SimulationError("Use an ordered date range of at most 366 calendar days.")
        symbol = normalize_symbol(body.symbol)
        safe_ticker_component(symbol)
        rows = body.model_dump()["rows"]
        dates = set()
        for row in rows:
            day = date.fromisoformat(_validate_trade_date(row["date"]))
            if not start <= day <= end or row["date"] in dates or Decimal(row["price"]) <= 0:
                raise SimulationError(
                    "Scenario rows need unique in-range dates and positive prices."
                )
            dates.add(row["date"])
        if body.source == "scenario" and not rows:
            raise SimulationError("Provide at least one scenario row.")
        if body.source == "research" and rows:
            raise SimulationError("Research mode uses historical quotes, not scenario rows.")
        return {**body.model_dump(exclude={"resume_id"}), "symbol": symbol}

    def list(self):
        with self.service.lock:
            self.service.ownership()
            folder = self.service.path("jobs")
            if not folder.is_dir():
                return []
            items = []
            for entry in folder.iterdir():
                if re.fullmatch(r"sim_[a-f0-9]{12}", entry.name):
                    items.append(self.get(entry.name))
            return sorted(items, key=lambda item: item["created_at"], reverse=True)[:100]

    def get(self, job_id):
        with self.service.lock:
            if not re.fullmatch(r"sim_[a-f0-9]{12}", job_id):
                raise SimulationError("Unknown simulation run.")
            path = self.service.path("jobs", job_id, "run.json")
            if not path.is_file():
                raise SimulationError("Unknown simulation run.")
            value = json.loads(path.read_text())
            if (
                not isinstance(value, dict)
                or value.get("run_id") != job_id
                or not isinstance(value.get("parameters"), dict)
                or not isinstance(value.get("policy_hash"), str)
            ):
                raise SimulationError("Saved simulation metadata is unavailable.")
            if value.get("status") in {"starting", "running"} and job_id not in self.running:
                value["status"] = "interrupted"
            return value

    def start(self, body):
        parameters = self.validate(body)
        config = effective_defaults() if body.source == "research" else {}
        policy_hash = hashlib.sha256(
            json.dumps(
                {"config": config, "policy": public(self.service.policy)},
                sort_keys=True,
                default=str,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        with self.service.lock:
            self.service.ownership()
            job_id = body.resume_id or f"sim_{uuid.uuid4().hex[:12]}"
            if body.resume_id:
                old = self.get(job_id)
                if old["parameters"] != parameters or old["policy_hash"] != policy_hash:
                    raise SimulationError(
                        "Resume requires identical inputs and server configuration."
                    )
                if old["status"] not in {"interrupted", "failed", "completed"}:
                    raise SimulationError("This simulation is already running.")
            folder = self.service.path("jobs", job_id)
            record = {
                "run_id": job_id,
                "kind": "simulation",
                "status": "starting",
                "parameters": parameters,
                "policy_hash": policy_hash,
                "created_at": self.service.clock.now().isoformat(),
                "summary": None,
                "snapshot": None,
                "error": None,
            }
            lease = self.service.coordinator.external_run(
                job_id, {"status": "running", "ticker": parameters["symbol"]}
            )
            lease.__enter__()
            try:
                folder.mkdir(parents=True, exist_ok=True)
                write_json(self.service.path("jobs", job_id, "run.json"), record)
                self.running[job_id] = record
                threading.Thread(
                    target=self._execute,
                    args=(record, config, lease),
                    daemon=True,
                    name=f"web-simulation-{job_id}",
                ).start()
            except BaseException:
                self.running.pop(job_id, None)
                lease.__exit__(None, None, None)
                raise
            return dict(record)

    def _execute(self, record, config, lease):
        job_id, parameters = record["run_id"], record["parameters"]
        runtime = None
        try:
            record["status"] = "running"
            write_json(self.service.path("jobs", job_id, "run.json"), record)
            start, end = (
                date.fromisoformat(parameters["start"]),
                date.fromisoformat(parameters["end"]),
            )
            clock = SimulationClock(start)
            root = self.service.path("jobs", job_id)
            runtime = build_runtime(
                RuntimeConfig(
                    self.service.path("jobs", job_id, "state.json"),
                    self.service.path("jobs", job_id, "audit.jsonl"),
                    Decimal(parameters["initial_cash"]),
                    self.service.policy,
                ),
                clock,
            )
            if runtime.cursor and runtime.cursor.last_completed_date:
                clock.set_date(runtime.cursor.last_completed_date)
            # Refuse an uncertain post-fill/pre-save crash instead of replaying it.
            for event in runtime.audit.read_all():
                if (
                    event.event_type is EventType.ORDER_EXECUTED
                    and not runtime.portfolio.has_applied(event.payload["order_id"])
                ):
                    raise SimulationError("Simulation state needs reconciliation before resuming.")
            decision_provider: DecisionProvider
            quote_provider: QuoteProvider
            if parameters["source"] == "scenario":
                decisions = {
                    date.fromisoformat(row["date"]): DecisionAction(row["action"])
                    for row in parameters["rows"]
                }
                prices = {
                    date.fromisoformat(row["date"]): Decimal(row["price"])
                    for row in parameters["rows"]
                }
                decision_provider, quote_provider = (
                    MockDecisionProvider(decisions),
                    MockQuoteProvider(prices),
                )
            else:
                from tradingagents.dataflows.config import set_config
                from tradingagents.dataflows.stockstats_utils import load_ohlcv

                config = {
                    **config,
                    "results_dir": str(root / "research"),
                    "memory_log_path": str(root / "research_memory.md"),
                    "data_cache_dir": str(root / "cache"),
                }
                set_config(config)

                def close(symbol, day):
                    data = load_ohlcv(symbol, day.isoformat(), fill_gaps=False)
                    rows = data[data["Date"].astype(str).str[:10] == day.isoformat()]
                    return None if rows.empty else str(rows.iloc[-1]["Close"])

                from cli.utils import detect_asset_type

                asset_type = detect_asset_type(parameters["symbol"]).value
                selected = ["market", "social", "news"] + (
                    ["fundamentals"] if asset_type == "stock" else []
                )
                decision_provider = RealDecisionProvider(
                    lambda: WebAnalysisGraph(
                        config=config, selected_analysts=selected, debug=False
                    ),
                    asset_type=asset_type,
                )
                quote_provider = HistoricalQuoteProvider(close)
            runner = BacktestRunner(
                pipeline=runtime.pipeline,
                engine=runtime.engine,
                state_store=runtime.store,
                decision_provider=decision_provider,
                quote_provider=quote_provider,
                calendar=WeekdayCalendar(),
                clock=clock,
                portfolio=runtime.portfolio,
                symbol=parameters["symbol"],
                start_date=start,
                end_date=end,
                run_id=job_id,
                initial_cash=Decimal(parameters["initial_cash"]),
            )
            if runtime.cursor is not None:
                runner._validate_cursor(runtime.cursor)
            if (
                runtime.cursor
                and runtime.cursor.last_completed_date
                and runtime.cursor.last_completed_date >= end
            ):
                snapshot = runtime.portfolio.snapshot()
                # A completed cursor has no remaining calendar interval to run.
                result = BacktestResult(
                    run_id=job_id,
                    symbol=parameters["symbol"],
                    start_date=start,
                    end_date=end,
                    days_processed=0,
                    days_skipped=0,
                    executions=0,
                    rejections=0,
                    pending_approvals=0,
                    no_actions=0,
                    final_equity=snapshot.total_equity,
                    bankrupt=snapshot.bankrupt,
                )
            else:
                result = runner.run()
            record["summary"] = public(result)
            record["status"] = "completed"
        except Exception as exc:
            failure = run_failure(exc, "simulated_backtest")
            record["status"] = "failed"
            record["error"] = (
                "Simulation could not finish. Check its audit and server configuration before resuming."
                + f" ({failure['correlation_id']})"
            )
        finally:
            if runtime:
                try:
                    portfolio, cursor = runtime.store.load()
                    record["snapshot"] = public(portfolio.snapshot())
                    record["cursor"] = public(cursor)
                except Exception:
                    record["error"] = "Simulation state needs reconciliation before resuming."
                    record["status"] = "failed"
            try:
                write_json(self.service.path("jobs", job_id, "run.json"), record)
            finally:
                with self.service.lock:
                    self.running.pop(job_id, None)
                lease.__exit__(None, None, None)
