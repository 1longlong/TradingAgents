"""Authoritative safety-engine orchestration for simulated trading."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from safety.rules import (
    DEFAULT_APPROVAL_POLICIES,
    DEFAULT_SAFETY_RULES,
    ApprovalPolicy,
    SafetyRule,
)
from trading.audit import AuditLog
from trading.clock import Clock, SystemClock
from trading.executor import SimulatedExecutor
from trading.models import (
    ApprovalCheck,
    ApprovalExpiredError,
    ApprovalMismatchError,
    DecisionAction,
    DecisionStatus,
    EvaluationResult,
    EventType,
    ExecutionAuthorization,
    ExecutionResult,
    HumanApproval,
    IllegalExecutionStateError,
    MarketQuote,
    OrderIntent,
    RuleContext,
    RuleResult,
    SafetyConfig,
    Side,
    StaleEvaluationError,
    TradeDecision,
    quantize_money,
    to_decimal,
)
from trading.portfolio import Portfolio


class _ProvenanceToken:
    """The unforgeable identity of this engine module's authorization issuer."""

    __slots__ = ()


_ENGINE_TOKEN = _ProvenanceToken()


@dataclass(frozen=True)
class _AuthorizedExecution(ExecutionAuthorization):
    provenance_token: object = field(default=None, repr=False, compare=False)


def _uuid_hex() -> str:
    return uuid.uuid4().hex


class SafetyEngine:
    """Run deterministic rules, manage approvals, and gate execution."""

    def __init__(
        self,
        config: SafetyConfig,
        portfolio: Portfolio,
        audit: AuditLog,
        *,
        rules: Sequence[SafetyRule] = DEFAULT_SAFETY_RULES,
        approval_policies: Sequence[ApprovalPolicy] = DEFAULT_APPROVAL_POLICIES,
        clock: Clock | None = None,
        evaluation_id_factory: Callable[[], str] = _uuid_hex,
        execution_id_factory: Callable[[], str] = _uuid_hex,
    ) -> None:
        self._config = config
        self._portfolio = portfolio
        self._audit = audit
        self._clock = clock or SystemClock()
        self._approval_policies = tuple(approval_policies)
        self._evaluation_id_factory = evaluation_id_factory
        self._resolved_approvals: set[str] = set()
        rules = tuple(rules)
        self._rules = tuple(
            rule for rule in rules if rule.rule_id == "SR-09"
        ) + tuple(rule for rule in rules if rule.rule_id != "SR-09")
        self._executor = SimulatedExecutor(
            portfolio,
            audit,
            authorization_token=_ENGINE_TOKEN,
            clock=self._clock.now,
            id_factory=execution_id_factory,
        )

    @property
    def execution_count(self) -> int:
        return self._executor.execution_count

    def evaluate(self, decision: TradeDecision, quote: MarketQuote) -> EvaluationResult:
        if not isinstance(decision, TradeDecision):
            raise IllegalExecutionStateError("decision must be a TradeDecision")
        if not isinstance(quote, MarketQuote):
            raise IllegalExecutionStateError("quote must be a MarketQuote")

        evaluation_id = self._next_evaluation_id()
        now = self._clock.now()
        snapshot = self._portfolio.snapshot()
        run_id = self._audit_run_id(decision, evaluation_id)

        self._audit.append(
            run_id=run_id,
            event_type=EventType.DECISION_RECEIVED,
            payload={
                "evaluation_id": evaluation_id,
                "decision": self._decision_payload(decision),
                "quote": self._quote_payload(quote),
                "portfolio_version": snapshot.version,
            },
        )

        if decision.action in (DecisionAction.HOLD, DecisionAction.REVIEW):
            reasons = (f"{decision.action.value} is advisory; no execution",)
            evaluation = self._make_evaluation(
                evaluation_id=evaluation_id,
                decision=decision,
                order_intent=None,
                status=DecisionStatus.NO_ACTION,
                rule_results=(),
                approval_checks=(),
                reasons=reasons,
                portfolio_version=snapshot.version,
                created_at=now,
            )
            self._audit_evaluated(evaluation, run_id)
            return evaluation

        order_intent = self._build_intent(decision, quote)
        order_id = (
            f"ord-{decision.decision_id}"
            if isinstance(decision.decision_id, str) and decision.decision_id.strip()
            else None
        )
        context = RuleContext(
            decision=decision,
            quote=quote,
            config=self._config,
            portfolio=snapshot,
            order_intent=order_intent,
            now=now,
            is_simulated=self._clock.is_simulated(),
            order_id=order_id,
            applied_order_ids=self._portfolio.applied_order_ids,
        )

        rule_results = tuple(rule.evaluate(context) for rule in self._rules)
        for result in rule_results:
            self._audit.append(
                run_id=run_id,
                event_type=EventType.RULE_EVALUATED,
                payload={
                    "evaluation_id": evaluation_id,
                    "decision_id": decision.decision_id,
                    "rule_id": result.rule_id,
                    "passed": result.passed,
                    "reason": result.reason,
                },
            )

        failures = tuple(result for result in rule_results if not result.passed)
        if failures:
            evaluation = self._make_evaluation(
                evaluation_id=evaluation_id,
                decision=decision,
                order_intent=order_intent,
                status=DecisionStatus.REJECTED,
                rule_results=rule_results,
                approval_checks=(),
                reasons=tuple(result.reason for result in failures),
                portfolio_version=snapshot.version,
                created_at=now,
            )
            self._audit_evaluated(evaluation, run_id)
            self._audit_decision(evaluation, run_id)
            return evaluation

        approval_checks = tuple(
            policy.evaluate(context) for policy in self._approval_policies
        )
        for check in approval_checks:
            self._audit.append(
                run_id=run_id,
                event_type=EventType.APPROVAL_POLICY_EVALUATED,
                payload={
                    "evaluation_id": evaluation_id,
                    "decision_id": decision.decision_id,
                    "policy_id": check.policy_id,
                    "triggered": check.triggered,
                    "reason": check.reason,
                },
            )

        triggered = tuple(check for check in approval_checks if check.triggered)
        status = (
            DecisionStatus.PENDING_APPROVAL
            if triggered
            else DecisionStatus.APPROVED
        )
        reasons = tuple(check.reason for check in triggered)
        evaluation = self._make_evaluation(
            evaluation_id=evaluation_id,
            decision=decision,
            order_intent=order_intent,
            status=status,
            rule_results=rule_results,
            approval_checks=approval_checks,
            reasons=reasons,
            portfolio_version=snapshot.version,
            created_at=now,
        )
        self._audit_evaluated(evaluation, run_id)
        if status is DecisionStatus.APPROVED:
            self._audit_decision(evaluation, run_id)
        return evaluation

    def apply_approval(
        self,
        evaluation: EvaluationResult,
        approval: HumanApproval,
    ) -> EvaluationResult:
        if not isinstance(evaluation, EvaluationResult):
            raise IllegalExecutionStateError("evaluation is required")
        if evaluation.status is not DecisionStatus.PENDING_APPROVAL:
            raise IllegalExecutionStateError("evaluation is not pending approval")
        if evaluation.evaluation_id in self._resolved_approvals:
            raise IllegalExecutionStateError("approval was already applied")
        if not isinstance(approval, HumanApproval):
            raise ApprovalMismatchError("a HumanApproval is required")
        if approval.decision_id != evaluation.decision.decision_id:
            raise ApprovalMismatchError("approval does not match the decision")
        if not approval.request_id.strip():
            raise ApprovalMismatchError("approval request id is required")
        if not approval.approver.strip():
            raise ApprovalMismatchError("approval approver is required")
        if not approval.reason.strip():
            raise ApprovalMismatchError("approval reason is required")
        if not isinstance(approval.approved, bool):
            raise ApprovalMismatchError("approval decision must be boolean")

        now = self._clock.now()
        expires_at = approval.expires_at
        if (
            not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or expires_at.utcoffset() is None
        ):
            raise ApprovalMismatchError("approval expiry is invalid")
        if now > expires_at:
            raise ApprovalExpiredError("approval has expired")

        if approval.approved:
            status = DecisionStatus.APPROVED
            reasons = ()
        else:
            status = DecisionStatus.REJECTED
            reasons = evaluation.reasons + (
                f"human approval denied: {approval.reason}",
            )

        updated = replace(
            evaluation,
            status=status,
            reasons=reasons,
            created_at=now,
        )
        self._audit_decision(
            updated,
            self._audit_run_id(updated.decision, evaluation.evaluation_id),
        )
        self._resolved_approvals.add(evaluation.evaluation_id)
        return updated

    def execute(self, evaluation: EvaluationResult) -> ExecutionResult:
        if not isinstance(evaluation, EvaluationResult):
            raise IllegalExecutionStateError("evaluation is required")
        if evaluation.status is not DecisionStatus.APPROVED:
            raise IllegalExecutionStateError(
                "only an APPROVED evaluation may be executed"
            )
        if evaluation.order_intent is None:
            raise IllegalExecutionStateError("approved evaluation has no order intent")
        if evaluation.portfolio_version != self._portfolio.version:
            raise StaleEvaluationError(
                "portfolio changed after the evaluation was produced"
            )

        authorization = _AuthorizedExecution(
            evaluation_id=evaluation.evaluation_id,
            decision=evaluation.decision,
            order_intent=evaluation.order_intent,
            portfolio_version=evaluation.portfolio_version,
            provenance_token=_ENGINE_TOKEN,
        )
        return self._executor.execute(authorization)

    def _next_evaluation_id(self) -> str:
        evaluation_id = str(self._evaluation_id_factory())
        if not evaluation_id.strip():
            raise IllegalExecutionStateError("evaluation id must be non-empty")
        return evaluation_id

    @staticmethod
    def _audit_run_id(decision: TradeDecision, evaluation_id: str) -> str:
        if isinstance(decision.run_id, str) and decision.run_id.strip():
            return decision.run_id
        return f"invalid-run-{evaluation_id}"

    @staticmethod
    def _decision_payload(decision: TradeDecision) -> dict:
        return {
            "run_id": decision.run_id,
            "decision_id": decision.decision_id,
            "symbol": decision.symbol,
            "action": decision.action.value,
            "quantity": (
                str(decision.quantity) if decision.quantity is not None else None
            ),
            "order_type": decision.order_type.value,
            "source": decision.source,
        }

    @staticmethod
    def _quote_payload(quote: MarketQuote) -> dict:
        return {
            "symbol": quote.symbol,
            "price": str(quote.price),
            "as_of": quote.as_of.isoformat(),
        }

    def _build_intent(
        self,
        decision: TradeDecision,
        quote: MarketQuote,
    ) -> OrderIntent | None:
        if decision.action not in (DecisionAction.BUY, DecisionAction.SELL):
            return None
        if decision.quantity is None:
            return None
        try:
            quantity = to_decimal(decision.quantity, field="quantity")
            price = to_decimal(quote.price, field="price")
            notional = quantize_money(quantity * price)
            fee = self._config.fee_model().fee_for(notional)
            return OrderIntent(
                decision_id=decision.decision_id,
                symbol=decision.symbol,
                side=(
                    Side.BUY
                    if decision.action is DecisionAction.BUY
                    else Side.SELL
                ),
                quantity=quantity,
                price=price,
                notional=notional,
                fee=fee,
            )
        except Exception:
            return None

    def _make_evaluation(
        self,
        *,
        evaluation_id: str,
        decision: TradeDecision,
        order_intent: OrderIntent | None,
        status: DecisionStatus,
        rule_results: tuple[RuleResult, ...],
        approval_checks: tuple[ApprovalCheck, ...],
        reasons: tuple[str, ...],
        portfolio_version: int,
        created_at: datetime,
    ) -> EvaluationResult:
        return EvaluationResult(
            evaluation_id=evaluation_id,
            decision=decision,
            order_intent=order_intent,
            status=status,
            rule_results=rule_results,
            approval_checks=approval_checks,
            reasons=reasons,
            portfolio_version=portfolio_version,
            created_at=created_at,
        )

    def _audit_evaluated(self, evaluation: EvaluationResult, run_id: str) -> None:
        self._audit.append(
            run_id=run_id,
            event_type=EventType.DECISION_EVALUATED,
            payload={
                "evaluation_id": evaluation.evaluation_id,
                "decision_id": evaluation.decision.decision_id,
                "status": evaluation.status.value,
                "reasons": list(evaluation.reasons),
                "rule_results": [
                    {
                        "rule_id": result.rule_id,
                        "passed": result.passed,
                        "reason": result.reason,
                    }
                    for result in evaluation.rule_results
                ],
                "approval_checks": [
                    {
                        "policy_id": check.policy_id,
                        "triggered": check.triggered,
                        "reason": check.reason,
                    }
                    for check in evaluation.approval_checks
                ],
                "portfolio_version": evaluation.portfolio_version,
            },
        )

    def _audit_decision(self, evaluation: EvaluationResult, run_id: str) -> None:
        event_type = (
            EventType.DECISION_APPROVED
            if evaluation.status is DecisionStatus.APPROVED
            else EventType.DECISION_REJECTED
        )
        self._audit.append(
            run_id=run_id,
            event_type=event_type,
            payload={
                "evaluation_id": evaluation.evaluation_id,
                "decision_id": evaluation.decision.decision_id,
                "status": evaluation.status.value,
                "reasons": list(evaluation.reasons),
                "portfolio_version": evaluation.portfolio_version,
            },
        )
