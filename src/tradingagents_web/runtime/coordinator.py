"""Single active analysis run, worker-thread bridge, and SSE replay."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tradingagents.agents.utils.rating import RATING_REVIEW, is_review, parse_rating

from .artifacts_writer import RunArtifactWriter
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
    cancel_event: threading.Event = field(default_factory=threading.Event)
    buffer: EventBuffer = field(default_factory=EventBuffer)
    writer: RunArtifactWriter | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def to_snapshot(self) -> dict:
        request = self.request
        return {
            "run_id": self.run_id,
            "status": self.status,
            "ticker": request.get("ticker"),
            "trade_date": request.get("trade_date"),
            "asset_type": request.get("asset_type", "stock"),
            "analysts": request.get("analysts", []),
            "research_depth": request.get("research_depth"),
            "llm_provider": request.get("llm_provider"),
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
            "error": self.error,
        }


class RunCoordinator:
    def __init__(self, settings, runner_factory):
        self.settings = settings
        self.runner_factory = runner_factory
        self._lock = threading.Lock()
        self._active: RunRecord | None = None
        self._records: dict[str, RunRecord] = {}
        self._request_ids: dict[str, str] = {}

    def start(self, request: dict, client_request_id: str) -> RunRecord:
        with self._lock:
            if self._active is not None and self._active.status not in TERMINAL_STATUSES:
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

    def _execute(self, record: RunRecord) -> None:
        record.writer = RunArtifactWriter(
            self.settings.results_dir,
            str(record.request["ticker"]),
            str(record.request["trade_date"]),
        )

        def emit(event: dict) -> None:
            self._emit(record, event)

        try:
            factory = self.runner_factory
            if isinstance(factory, type) or (callable(factory) and not hasattr(factory, "run")):
                runner = factory()
            else:
                runner = factory
            runner.run(record.request, emit, record.cancel_event)
        except Exception:
            emit(
                {
                    "type": "run.failed",
                    "payload": {
                        "category": "internal",
                        "message": "analysis failed; check the server log",
                    },
                }
            )
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

        with record.lock:
            if event_type == "run.completed":
                final_state = payload.pop("final_state", None)
                if record.writer is not None:
                    try:
                        record.writer.complete(final_state)
                    except Exception:
                        record.warnings.append("report_save_failed")
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
                record.wall_times = payload.get("wall_times") or {}
            elif event_type == "message" and record.writer is not None:
                record.writer.on_message(payload)
            elif event_type == "tool_call" and record.writer is not None:
                record.writer.on_tool_call(payload)
            elif event_type == "report.section" and record.writer is not None:
                record.writer.on_section(payload)

            stored = record.buffer.append(
                {
                    "run_id": record.run_id,
                    "timestamp": _now(),
                    "type": event_type,
                    "payload": payload,
                }
            )
            record.last_seq = stored["seq"]
            if event_type == "run.started":
                record.status = "running"
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

        if record.status in TERMINAL_STATUSES:
            with self._lock:
                if self._active is record:
                    self._active = None

    def cancel(self, run_id: str) -> RunRecord | None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return None
            record.cancel_event.set()
            if record.status not in TERMINAL_STATUSES:
                record.status = "cancelling"
            return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(run_id)

    def active_snapshot(self) -> dict | None:
        with self._lock:
            record = self._active
            if record is None or record.status in TERMINAL_STATUSES:
                return None
            return record.to_snapshot()

    async def stream(self, run_id: str, after_seq: int):
        record = self.get(run_id)
        if record is None:
            raise RunNotFound(run_id)
        cursor = after_seq
        while True:
            events = record.buffer.since(cursor)
            for event in events:
                cursor = max(cursor, event["seq"])
                yield event
            if record.status in TERMINAL_STATUSES and record.buffer.last_seq <= cursor:
                return
            await asyncio.sleep(0.02)
