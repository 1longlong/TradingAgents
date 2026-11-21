"""FR-TRD-001..006, INV-TRD-001..003; ADR-001-simulated-trading-system.md.

Web composition only: the existing pipeline/approval gate/engine own decisions.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from trading.clock import SystemClock
from trading.models import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    DecisionStatus,
    EventType,
    MarketQuote,
    SafetyConfig,
)
from trading.runtime import RuntimeConfig, build_runtime
from tradingagents_web.artifacts.downloads import read_text, section_file
from tradingagents_web.artifacts.index import ArtifactIndex
from tradingagents_web.models.simulation_requests import SimulationError
from tradingagents_web.security import redact_obj


def public(value):
    """Serialize core Decimal/date/enum values without binary float conversion."""
    if is_dataclass(value) and not isinstance(value, type):
        return public(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [public(item) for item in value]
    return value


def write_json(path: Path, value):
    """Atomic Web metadata; core portfolio/audit persistence stays authoritative."""
    temporary = path.with_suffix(".tmp")
    if temporary.is_symlink():
        raise SimulationError("Simulation storage is unavailable.")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(public(value), stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class SimulationService:
    def __init__(self, settings, coordinator, *, clock=None):
        self.settings, self.coordinator = settings, coordinator
        self.root = Path(settings.results_dir) / "simulated_trading"
        self.lock = threading.RLock()
        self.clock = clock or SystemClock()
        self.policy = SafetyConfig()
        self.runtime = None
        self.pending = {}
        self.receipts = None
        self.poisoned = False
        self.owner = None
        self.state_signature = None
        self.account_id = None
        from .simulation_jobs import SimulationJobs

        self.jobs = SimulationJobs(self)

    def path(self, *parts):
        root = self.root.resolve()
        if not root.is_relative_to(Path(self.settings.results_dir).resolve()):
            raise SimulationError("Simulation storage is unavailable.")
        candidate = self.root.joinpath(*parts)
        if not candidate.resolve().is_relative_to(root):
            raise SimulationError("Simulation storage is unavailable.")
        return candidate

    def ownership(self):
        if self.owner is not None:
            return
        self.path().mkdir(parents=True, exist_ok=True)
        owner = self.path("owner.lock").open("a")
        try:
            fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            owner.close()
            raise SimulationError("Another server owns this simulation workspace.") from None
        self.owner = owner

    def close(self):
        with self.lock:
            if self.jobs.running:
                return
            if self.owner is not None:
                self.owner.close()
                self.owner = None

    def runtime_config(self, cash=None, directory="account"):
        self.path(directory).mkdir(parents=True, exist_ok=True)
        for name in ("state.json", "state.tmp", "audit.jsonl", "audit.jsonl.head"):
            self.path(directory, name)
        if cash is None:
            location = self.path(directory, "state.json")
            saved = json.loads(location.read_text()) if location.is_file() else {}
            cash = saved.get("initial_cash", "100000.00")
            if not isinstance(cash, str):
                raise SimulationError("Simulation storage is unavailable.")
        return RuntimeConfig(
            self.path(directory, "state.json"),
            self.path(directory, "audit.jsonl"),
            Decimal(cash),
            self.policy,
        )

    def load(self):
        self.ownership()
        if self.poisoned:
            raise SimulationError("Simulation state needs reconciliation before further changes.")
        if self.runtime is None and self.path("account", "state.json").is_file():
            self.runtime = build_runtime(self.runtime_config(), self.clock)
            events = self.runtime.audit.read_all()
            # A crash after a fill but before state persistence must not replay it.
            for event in reversed(events):
                if event.event_type is EventType.STATE_RESET:
                    break
                if event.event_type is EventType.ORDER_EXECUTED:
                    order_id = event.payload.get("order_id")
                    if not order_id or not self.runtime.portfolio.has_applied(order_id):
                        self.poisoned = True
                        raise SimulationError(
                            "Simulation state needs reconciliation before further changes."
                        )
        if self.runtime is not None:
            context_path = self.path("account", "context.json")
            if not context_path.is_file():
                raise SimulationError(
                    "Simulation state needs reconciliation before further changes."
                )
            context = json.loads(context_path.read_text())
            if not isinstance(context, dict) or not re.fullmatch(
                r"[a-f0-9]{32}", str(context.get("account_id", ""))
            ):
                raise SimulationError("Simulation storage is unavailable.")
            resets = [
                event.event_id
                for event in self.runtime.audit.read_all()
                if event.event_type is EventType.STATE_RESET
            ]
            if context.get("reset_event_id") != (resets[-1] if resets else None):
                raise SimulationError(
                    "Simulation state needs reconciliation before further changes."
                )
            self.account_id = context["account_id"]
            self.runtime.audit.verify_integrity()
            location = self.path("account", "state.json")
            info = location.stat()
            signature = (info.st_ino, info.st_mtime_ns, info.st_size)
            if self.state_signature is not None and signature != self.state_signature:
                self.poisoned = True
                raise SimulationError(
                    "Simulation state changed outside this server. Reconciliation is required."
                )
            self.state_signature = signature
        if self.receipts is None:
            location = self.path("requests.json")
            self.receipts = json.loads(location.read_text()) if location.is_file() else {}
            if not isinstance(self.receipts, dict):
                raise SimulationError("Simulation request history is unavailable.")
        return self.runtime

    def state(self):
        with self.lock:
            runtime = self.load()
            return {
                "initialized": runtime is not None,
                "account_id": self.account_id if runtime else None,
                "snapshot": public(runtime.portfolio.snapshot()) if runtime else None,
                "policy": public(self.policy),
                "pending": self.pending_items(),
                "transactions": list((self.receipts or {}).values())[-100:][::-1],
            }

    def pending_items(self):
        runtime = self.runtime
        if runtime is None:
            return []
        now = self.clock.now()
        result = []
        for request_id, (record, quote, receipt_id) in self.pending.items():
            status = "pending"
            if record.approval_request.expires_at <= now:
                status = "expired"
            elif runtime.portfolio.version != record.evaluation.portfolio_version:
                status = "stale"
            elif (now - quote.as_of).total_seconds() > self.policy.max_quote_age_seconds:
                status = "stale_quote"
            result.append(
                {
                    "request_id": request_id,
                    "state": status,
                    "receipt_id": receipt_id,
                    "evaluation": public(record.evaluation),
                    "request": public(record.approval_request),
                }
            )
        return result

    def account(self, body):
        with self.coordinator.external_run("sim_account", {"status": "running"}), self.lock:
            self.ownership()
            exists = self.path("account", "state.json").is_file()
            if body.confirm == "INITIALIZE" and exists:
                raise SimulationError("The simulated account is already initialized.")
            if body.confirm == "RESET":
                self._version(body.expected_version, body.expected_account_id)
            self.runtime = build_runtime(
                self.runtime_config(body.initial_cash), self.clock, reset=body.confirm == "RESET"
            )
            self.runtime.store.save(self.runtime.portfolio)
            info = self.path("account", "state.json").stat()
            self.state_signature = (info.st_ino, info.st_mtime_ns, info.st_size)
            resets = [
                event.event_id
                for event in self.runtime.audit.read_all()
                if event.event_type is EventType.STATE_RESET
            ]
            self.account_id = uuid.uuid4().hex
            try:
                write_json(
                    self.path("account", "context.json"),
                    {
                        "account_id": self.account_id,
                        "reset_event_id": resets[-1] if resets else None,
                    },
                )
            except Exception:
                self.poisoned = True
                raise
            self.pending.clear()
            self.poisoned = False
            self.receipts = self.receipts or {}
            return self.state()

    def _version(self, version, account_id):
        runtime = self.load()
        if runtime is None:
            raise SimulationError("Initialize the simulated account first.")
        if version != runtime.portfolio.version or account_id != self.account_id:
            raise SimulationError("Account version changed. Refresh and evaluate again.")
        return runtime

    def _persist(self, receipt_id, value):
        if self.runtime is None or self.receipts is None:
            raise SimulationError("Initialize the simulated account first.")
        try:
            self.runtime.store.save(self.runtime.portfolio)
            info = self.path("account", "state.json").stat()
            self.state_signature = (info.st_ino, info.st_mtime_ns, info.st_size)
            self.receipts[receipt_id] = value
            write_json(self.path("requests.json"), self.receipts)
        except Exception:
            self.poisoned = True
            raise

    def decision(self, body):
        with self.coordinator.external_run("sim_decision", {"status": "running"}), self.lock:
            runtime = self.load()
            if self.receipts is None:
                raise SimulationError("Simulation request history is unavailable.")
            previous = self.receipts.get(body.client_request_id)
            submitted = body.model_dump()
            if previous:
                if previous.get("input") != submitted:
                    raise SimulationError("This request ID was already used with different inputs.")
                return previous
            runtime = self._version(body.expected_version, body.expected_account_id)
            artifact = ArtifactIndex(self.settings).find(body.artifact_id)
            if (
                artifact is None
                or artifact.status != "completed"
                or artifact.source not in {"run", "saved"}
            ):
                raise SimulationError("Choose a completed analysis report.")
            section = "final_trade_decision" if artifact.source == "run" else "5_portfolio/decision"
            text = read_text(section_file(artifact, section), self.settings.max_report_bytes)
            if not text:
                raise SimulationError("This report has no final portfolio decision.")
            as_of = datetime.fromisoformat(body.quote_as_of.replace("Z", "+00:00"))
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise SimulationError("Quote time must include a timezone.")
            quote = MarketQuote(artifact.ticker, Decimal(body.quote_price), as_of)
            try:
                result = runtime.pipeline.process(
                    {"final_trade_decision": text, "trade_date": artifact.date},
                    quote,
                    run_id=f"web_{body.client_request_id}",
                    symbol=artifact.ticker,
                )
            except Exception:
                self.poisoned = True
                raise
            value = {
                "id": body.client_request_id,
                "input": submitted,
                "ticker": artifact.ticker,
                "created_at": self.clock.now().isoformat(),
                "result": public(result),
            }
            if result.approval_request:
                self.pending[result.approval_request.request_id] = (
                    result,
                    quote,
                    body.client_request_id,
                )
            self._persist(body.client_request_id, value)
            return value

    def approve(self, request_id, body):
        with self.coordinator.external_run("sim_approval", {"status": "running"}), self.lock:
            runtime = self._version(body.expected_version, body.expected_account_id)
            item = self.pending.get(request_id)
            if item is None:
                raise SimulationError(
                    "Approval is unavailable or belongs to an earlier server process. Evaluate again."
                )
            record, quote, receipt_id = item
            if self.receipts is None:
                raise SimulationError("Simulation request history is unavailable.")
            if runtime.portfolio.version != record.evaluation.portfolio_version:
                raise SimulationError("The approval is stale. Evaluate again.")
            if (
                body.approved
                and (self.clock.now() - quote.as_of).total_seconds()
                > self.policy.max_quote_age_seconds
            ):
                raise SimulationError("The scenario quote is stale. Evaluate again.")
            if not body.approver.strip() or not body.reason.strip():
                raise SimulationError("Provide your name and an approval reason.")
            try:
                approval = runtime.gate.decide(
                    record.approval_request,
                    approver=body.approver,
                    approved=body.approved,
                    reason=body.reason,
                )
                evaluation = runtime.engine.apply_approval(record.evaluation, approval)
                execution = (
                    runtime.engine.execute(evaluation)
                    if evaluation.status is DecisionStatus.APPROVED
                    else None
                )
            except (ApprovalExpiredError, ApprovalMismatchError):
                raise
            except Exception:
                self.poisoned = True
                raise
            value = {
                **self.receipts[receipt_id],
                "result": public(replace(record, evaluation=evaluation, execution=execution)),
                "approval": public(approval),
            }
            self._persist(receipt_id, value)
            self.pending.pop(request_id)
            return value

    def audit(self, *, run_id=None, kind=None, offset=0, limit=50):
        with self.lock:
            self.ownership()
            from trading.audit import AuditLog

            if run_id:
                if not isinstance(run_id, str) or not re.fullmatch(r"sim_[a-f0-9]{12}", run_id):
                    raise SimulationError("Unknown simulation run.")
                location = self.path("jobs", run_id, "audit.jsonl")
                if not location.is_file():
                    raise SimulationError("Unknown simulation audit.")
            else:
                location = self.path("account", "audit.jsonl")
                if not location.is_file():
                    return {"verified": None, "items": [], "total": 0}
            log = AuditLog(location, clock=self.clock.now)
            log.verify_integrity()
            events = [
                public(event)
                for event in reversed(log.read_all())
                if not kind or event.event_type.value == kind
            ]
            return {
                "verified": True,
                "items": redact_obj(events[offset : offset + limit]),
                "total": len(events),
            }
