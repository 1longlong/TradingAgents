"""Human-in-the-loop approval gate for pending safety evaluations."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from trading.audit import AuditLog
from trading.clock import Clock, SystemClock
from trading.models import (
    ApprovalExpiredError,
    ApprovalMismatchError,
    ApprovalRequest,
    DecisionStatus,
    EvaluationResult,
    EventType,
    HumanApproval,
    IllegalExecutionStateError,
    SafetyConfig,
)


def _uuid_hex() -> str:
    return uuid.uuid4().hex


@dataclass
class _PendingApproval:
    request: ApprovalRequest
    decision_id: str
    evaluation_id: str
    run_id: str
    decided: bool = False


class HumanApprovalGate:
    """Issue approval requests and record one human decision per evaluation."""

    def __init__(
        self,
        audit: AuditLog,
        config: SafetyConfig,
        *,
        clock: Clock | None = None,
        id_factory: Callable[[], str] = _uuid_hex,
    ) -> None:
        self._audit = audit
        self._config = config
        self._clock = clock or SystemClock()
        self._id_factory = id_factory
        self._lock = threading.RLock()
        self._requests: dict[str, _PendingApproval] = {}
        self._by_evaluation: dict[str, str] = {}

    def request(self, evaluation: EvaluationResult) -> ApprovalRequest:
        if not isinstance(evaluation, EvaluationResult):
            raise IllegalExecutionStateError("evaluation is required")
        if evaluation.status is not DecisionStatus.PENDING_APPROVAL:
            raise IllegalExecutionStateError(
                "only PENDING_APPROVAL evaluations can request approval"
            )
        if (
            not isinstance(evaluation.evaluation_id, str)
            or not evaluation.evaluation_id.strip()
        ):
            raise IllegalExecutionStateError("evaluation id is required")
        if (
            not isinstance(evaluation.decision.decision_id, str)
            or not evaluation.decision.decision_id.strip()
        ):
            raise IllegalExecutionStateError("decision id is required")

        with self._lock:
            if evaluation.evaluation_id in self._by_evaluation:
                raise IllegalExecutionStateError(
                    "an approval request already exists for this evaluation"
                )
            request_id = str(self._id_factory())
            if not request_id.strip():
                raise IllegalExecutionStateError("request id must be non-empty")
            if request_id in self._requests:
                raise IllegalExecutionStateError("duplicate approval request id")

            now = self._now()
            expires_at = now + timedelta(
                seconds=self._config.approval_ttl_seconds
            )
            request = ApprovalRequest(
                request_id=request_id,
                decision_id=evaluation.decision.decision_id,
                evaluation_id=evaluation.evaluation_id,
                created_at=now,
                expires_at=expires_at,
            )
            run_id = self._run_id(evaluation)
            self._audit.append(
                run_id=run_id,
                event_type=EventType.HUMAN_APPROVAL_REQUESTED,
                payload={
                    "request_id": request.request_id,
                    "evaluation_id": request.evaluation_id,
                    "decision_id": request.decision_id,
                    "created_at": request.created_at.isoformat(),
                    "expires_at": request.expires_at.isoformat(),
                    "status": DecisionStatus.PENDING_APPROVAL.value,
                },
            )
            pending = _PendingApproval(
                request=request,
                decision_id=request.decision_id,
                evaluation_id=request.evaluation_id,
                run_id=run_id,
            )
            self._requests[request_id] = pending
            self._by_evaluation[request.evaluation_id] = request_id
            return request

    def decide(
        self,
        request: ApprovalRequest,
        *,
        approver: str,
        approved: bool,
        reason: str,
    ) -> HumanApproval:
        if not isinstance(request, ApprovalRequest):
            raise ApprovalMismatchError("an ApprovalRequest is required")
        if not isinstance(approved, bool):
            raise ApprovalMismatchError("approved must be boolean")
        if not isinstance(approver, str) or not approver.strip():
            raise ApprovalMismatchError("approver must be non-empty")
        if not isinstance(reason, str) or not reason.strip():
            raise ApprovalMismatchError("reason must be non-empty")

        with self._lock:
            pending = self._requests.get(request.request_id)
            if pending is None:
                raise ApprovalMismatchError(
                    "approval request was not issued by this gate"
                )
            if request != pending.request:
                raise ApprovalMismatchError(
                    "approval request does not match the issued request"
                )
            if request.decision_id != pending.decision_id:
                raise ApprovalMismatchError(
                    "approval decision id does not match the evaluation"
                )
            if pending.decided:
                raise IllegalExecutionStateError(
                    "approval has already been decided"
                )

            now = self._now()
            if now >= pending.request.expires_at:
                raise ApprovalExpiredError("approval request has expired")

            approval = HumanApproval(
                request_id=pending.request.request_id,
                decision_id=pending.decision_id,
                approved=approved,
                approver=approver.strip(),
                reason=reason.strip(),
                decided_at=now,
                expires_at=pending.request.expires_at,
            )
            self._audit.append(
                run_id=pending.run_id,
                event_type=EventType.HUMAN_APPROVAL,
                payload={
                    "request_id": approval.request_id,
                    "evaluation_id": pending.evaluation_id,
                    "decision_id": approval.decision_id,
                    "approved": approval.approved,
                    "approver": approval.approver,
                    "reason": approval.reason,
                    "decided_at": approval.decided_at.isoformat(),
                    "expires_at": approval.expires_at.isoformat(),
                },
            )
            pending.decided = True
            return approval

    def _now(self) -> datetime:
        now = self._clock.now()
        if not isinstance(now, datetime):
            raise IllegalExecutionStateError("clock must return a datetime")
        if now.tzinfo is None or now.utcoffset() is None:
            raise IllegalExecutionStateError(
                "clock must return a timezone-aware datetime"
            )
        return now

    @staticmethod
    def _run_id(evaluation: EvaluationResult) -> str:
        run_id = evaluation.decision.run_id
        if isinstance(run_id, str) and run_id.strip():
            return run_id
        return f"invalid-run-{evaluation.evaluation_id}"
