"""Run lifecycle and recovery: ADR-001/007, REQ-WEB-005/007, INV-WEB-003/009."""

from __future__ import annotations

import asyncio
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tradingagents.agents.utils.rating import RATING_REVIEW, is_review, parse_rating
from tradingagents_web.errors import run_failure
from tradingagents_web.security import redact_obj

from .artifacts_writer import RunArtifactWriter
from .backtest_progress import BacktestProgress
from .event_buffer import EventBuffer

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class RunConflict(RuntimeError):
    def __init__(self, active_run_id: str):
        super().__init__(f"run already active: {active_run_id}")
        self.active_run_id = active_run_id


class RunNotFound(KeyError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    run_id: str
    request: dict
    portfolio_fingerprint: str | None = None
    checkpoint_enabled: bool = False
    status: str = "starting"
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    last_seq: int = 0
    signal: str | None = None
    review: bool = False
    wall_times: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: dict | None = None
    messages: list[dict] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    agents: dict[str, str] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    phase: str = "preparing"
    artifact_id: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    buffer: EventBuffer = field(default_factory=EventBuffer)
    writer: RunArtifactWriter | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def to_snapshot(self) -> dict:
        # Snapshot state and cursor must describe the same event (REQ-WEB-007).
        with self.lock:
            request = self.request
            return {
                "run_id": self.run_id,
                "status": self.status,
                "ticker": request.get("ticker"),
                "trade_date": request.get("trade_date"),
                "asset_type": request.get("asset_type", "stock"),
                "analysts": request.get("analysts", []),
                "research_depth": request.get("research_depth"),
                "debate_termination": dict(request.get("debate_termination") or {}),
                "max_risk_discuss_rounds": request.get("max_risk_discuss_rounds"),
                "llm_provider": request.get("llm_provider"),
                "output_language": request.get("output_language"),
                "quick_think_llm": request.get("quick_think_llm"),
                "deep_think_llm": request.get("deep_think_llm"),
                "checkpoint_enabled": self.checkpoint_enabled,
                "portfolio_fingerprint": self.portfolio_fingerprint,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "last_seq": self.last_seq,
                "signal": self.signal,
                "review": self.review,
                "wall_times": self.wall_times,
                "warnings": list(self.warnings),
                "error": dict(self.error) if self.error else None,
                "messages": [dict(message) for message in self.messages],
                "sections": dict(self.sections),
                "agents": dict(self.agents),
                "stats": dict(self.stats),
                "phase": self.phase,
                "artifact_id": self.artifact_id,
            }


@dataclass
class BacktestRecord:
    run_id: str
    request: dict
    status: str = "starting"
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    summary: dict | None = None
    error: dict | None = None
    cells_run: int = 0
    skipped: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    progress: BacktestProgress = field(init=False)

    def __post_init__(self):
        self.progress = BacktestProgress(
            list(self.request.get("tickers") or []), list(self.request.get("dates") or [])
        )

    def update_progress(self, event: dict):
        with self.lock:
            self.progress.update(event)

    def to_snapshot(self, cells_offset: int | None = None, cells_limit: int = 25) -> dict:
        with self.lock:
            return self._snapshot(cells_offset, cells_limit)

    def _snapshot(self, cells_offset: int | None, cells_limit: int) -> dict:
        request = self.request
        tickers = list(request.get("tickers") or [])
        dates = list(request.get("dates") or [])
        return {
            "run_id": self.run_id,
            "kind": "backtest",
            "status": self.status,
            "ticker": ",".join(tickers),
            "tickers": tickers,
            "dates": dates,
            "start": request.get("start"),
            "end": request.get("end"),
            "every": request.get("every"),
            "asset_type": request.get("asset_type", "stock"),
            "analysts": request.get("selected_analysts", []),
            "expected_cells": len(tickers) * len(dates),
            "cells_run": self.cells_run,
            "skipped": self.skipped,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "summary": self.summary,
            "error": self.error,
            "progress": self.progress.snapshot(cells_offset, cells_limit),
        }


@dataclass
class ExternalRunRecord:
    """FR-TRD-005, ADR-007-run-controls.md: share the existing serial slot."""

    run_id: str
    snapshot: dict

    def to_snapshot(self) -> dict:
        return {"run_id": self.run_id, "kind": "simulation", **self.snapshot}


class RunCoordinator:
    def __init__(self, settings, runner_factory):
        self.settings = settings
        self.runner_factory = runner_factory
        self._lock = threading.Lock()
        self._active: RunRecord | BacktestRecord | ExternalRunRecord | None = None
        self._records: dict[str, RunRecord] = {}
        self._backtests: dict[str, BacktestRecord] = {}
        self._request_ids: dict[str, str] = {}

    @contextmanager
    def external_run(self, run_id: str, snapshot: dict):
        """Hold the shared slot for a simulated transaction or background run."""
        record = ExternalRunRecord(run_id, snapshot)
        with self._lock:
            if self._active is not None:
                raise RunConflict(self._active.run_id)
            self._active = record
        try:
            yield record
        finally:
            with self._lock:
                if self._active is record:
                    self._active = None

    def start(self, request: dict, client_request_id: str) -> RunRecord:
        with self._lock:
            if self._active is not None:
                raise RunConflict(self._active.run_id)
            existing_id = self._request_ids.get(client_request_id)
            if existing_id and existing_id in self._records:
                return self._records[existing_id]

            run_id = f"r_{uuid.uuid4().hex[:12]}"
            record = RunRecord(
                run_id=run_id,
                request=request,
                portfolio_fingerprint=request.get("portfolio_fingerprint"),
                checkpoint_enabled=bool(request.get("config", {}).get("checkpoint_enabled")),
            )
            self._records[run_id] = record
            self._request_ids[client_request_id] = run_id
            self._active = record
            threading.Thread(
                target=self._execute,
                args=(record,),
                name=f"web-run-{run_id}",
                daemon=True,
            ).start()
            return record

    def start_backtest(self, request: dict) -> BacktestRecord:
        with self._lock:
            if self._active is not None:
                raise RunConflict(self._active.run_id)

            run_id = str(request["run_id"])
            record = BacktestRecord(run_id=run_id, request=request)
            self._backtests[run_id] = record
            self._active = record
            threading.Thread(
                target=self._execute_backtest,
                args=(record,),
                name=f"web-backtest-{run_id}",
                daemon=True,
            ).start()
            return record

    def _execute_backtest(self, record: BacktestRecord) -> None:
        with record.lock:
            record.status = "running"
        try:
            from .backtest_runner import BacktestRunner

            outcome = BacktestRunner(self.settings).execute(record.request, record.update_progress)
            with record.lock:
                record.summary = outcome["summary"]
                record.cells_run = int(outcome.get("cells_run") or 0)
                record.skipped = int(outcome.get("skipped") or 0)
                record.status = "completed"
                record.finished_at = _now()
                record.progress.finish("completed")
        except Exception as exc:
            # REQ-WEB-011, ADR-007: retain safe diagnostics before releasing the slot.
            failure = run_failure(exc, "backtest")
            with record.lock:
                record.status = "failed"
                record.error = failure
                record.finished_at = _now()
                record.progress.finish("failed")
        finally:
            with self._lock:
                if self._active is record:
                    self._active = None

    def get_backtest(self, run_id: str) -> BacktestRecord | None:
        with self._lock:
            return self._backtests.get(run_id)

    def backtest_snapshots(self) -> list[dict]:
        with self._lock:
            return [record.to_snapshot() for record in self._backtests.values()]

    def _execute(self, record: RunRecord) -> None:
        def emit(event: dict) -> None:
            self._emit(record, event)

        phase = "artifacts"
        try:
            record.writer = RunArtifactWriter(
                self.settings.results_dir,
                str(record.request["ticker"]),
                str(record.request["trade_date"]),
                record.run_id,
                metadata=record.request,
            )
            record.artifact_id = record.writer.artifact_id
            phase = "execution"
            factory = self.runner_factory
            if isinstance(factory, type) or (callable(factory) and not hasattr(factory, "run")):
                runner = factory()
            else:
                runner = factory
            runner.run(record.request, emit, record.cancel_event)
        except Exception as exc:
            emit({"type": "run.failed", "payload": run_failure(exc, phase)})
        finally:
            if record.status not in TERMINAL_STATUSES:
                if record.cancel_event.is_set():
                    emit(
                        {
                            "type": "run.cancelled",
                            "payload": {"message": "run cancelled"},
                        }
                    )
                else:
                    emit(
                        {
                            "type": "run.failed",
                            "payload": {
                                "category": "internal",
                                "message": "runner ended without a terminal event",
                            },
                        }
                    )
            with self._lock:
                if self._active is record:
                    self._active = None

    def _emit(self, record: RunRecord, event: dict) -> None:
        event_type = str(event.get("type") or "")
        payload = dict(event.get("payload") or {})
        final_state = payload.pop("final_state", None)
        payload = redact_obj(payload)

        with record.lock:
            if event_type == "run.completed":
                if record.writer is not None:
                    try:
                        record.writer.complete(final_state)
                    except Exception as exc:
                        record.warnings.append("report_save_failed")
                        run_failure(exc, "artifacts")
                    payload["warnings"] = list(record.warnings)
                    decision = record.writer.sections.get("final_trade_decision")
                else:
                    decision = None
                signal = payload.get("signal")
                if not signal and decision:
                    signal = parse_rating(decision)
                signal = signal or RATING_REVIEW
                payload["signal"] = signal
                payload["review"] = bool(payload.get("review", is_review(signal)))
                record.signal = signal
                record.review = bool(payload["review"])
                record.wall_times.update(payload.get("wall_times") or {})
                payload["artifact_id"] = record.artifact_id
            elif event_type == "message" and record.writer is not None:
                record.writer.on_message(payload)
            elif event_type == "tool_call" and record.writer is not None:
                record.writer.on_tool_call(payload)
            elif event_type == "report.section" and record.writer is not None:
                record.writer.on_section(payload)

            if event_type in {"message", "tool_call"}:
                message = dict(payload)
                message["id"] = f"{record.run_id}:{record.last_seq + 1}"
                if event_type == "tool_call":
                    message["type"] = "Tool"
                    message["content"] = (
                        f"{payload.get('name', 'tool')}({payload.get('arguments', {})})"
                    )
                record.messages.append(message)
                record.messages = record.messages[-500:]
            elif event_type == "report.section":
                record.sections[str(payload.get("section", ""))] = str(payload.get("content", ""))
            elif event_type == "agent.status":
                record.agents[str(payload.get("agent", ""))] = str(payload.get("status", ""))
            elif event_type == "analyst.timing":
                record.wall_times.update(payload.get("wall_times") or {})
            elif event_type == "stats":
                record.stats = payload
            elif event_type in {"run.preparing", "run.phase"}:
                record.phase = str(payload.get("phase", "preparing"))

            stored = record.buffer.append(
                {
                    "run_id": record.run_id,
                    "timestamp": _now(),
                    "type": event_type,
                    "payload": payload,
                }
            )
            record.last_seq = stored["seq"]
            if event_type in {"run.started", "run.resumed"}:
                record.status = "cancelling" if record.cancel_event.is_set() else "running"
                record.phase = "analysis"
            elif event_type == "run.completed":
                record.status = "completed"
                record.finished_at = _now()
            elif event_type == "run.failed":
                record.status = "failed"
                record.error = payload
                record.finished_at = _now()
            elif event_type == "run.cancelled":
                record.status = "cancelled"
                record.finished_at = _now()

            if (
                event_type
                in {"run.started", "run.resumed", "run.completed", "run.failed", "run.cancelled"}
                and record.writer
            ):
                try:
                    record.writer.set_status(record.status)
                except OSError as exc:
                    if "status_save_failed" not in record.warnings:
                        record.warnings.append("status_save_failed")
                    run_failure(exc, "artifacts")

    def cancel(self, run_id: str) -> RunRecord | None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return None
            with record.lock:
                if record.status not in TERMINAL_STATUSES:
                    record.cancel_event.set()
                    record.status = "cancelling"
            return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(run_id)

    def active_snapshot(self) -> dict | None:
        with self._lock:
            record = self._active
            if record is None:
                return None
            return record.to_snapshot()

    async def stream(self, run_id: str, after_seq: int):
        record = self.get(run_id)
        if record is None:
            raise RunNotFound(run_id)
        cursor = after_seq
        while True:
            with record.lock:
                first = record.buffer.first_seq()
                if first is not None and cursor < first - 1:
                    snapshot = record.to_snapshot()
                    events = [
                        {
                            "run_id": run_id,
                            "seq": snapshot["last_seq"],
                            "type": "snapshot",
                            "payload": snapshot,
                        }
                    ]
                else:
                    events = record.buffer.since(cursor)
                terminal = record.status in TERMINAL_STATUSES
            for event in events:
                cursor = max(cursor, event["seq"])
                yield event
            if terminal and record.buffer.last_seq <= cursor:
                return
            await asyncio.sleep(0.02)
