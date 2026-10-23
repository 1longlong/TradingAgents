"""Phase 3B debate-termination package.

Typed, deterministic, JSON-safe models and logic for dynamic Bull/Bear debate
termination:

- ``models`` — ``DebateTurn``, ``ConflictRecord``, ``StanceSnapshot``,
  ``RoundMetrics``, ``BudgetState``, ``RoutingDecision``.
- ``config`` — the validated ``debate_termination`` configuration group.
- ``evidence_manifest`` — valid-new-evidence rules against the gate manifest.
- ``budget`` — deterministic usage estimation / accounting.
- ``turn`` — structured metadata extraction for a single Bull/Bear turn.
- ``state`` — debate-state mutation helpers (researcher side).
- ``evaluator`` — the pure ``evaluate_round`` decision rules.
- ``evaluator_node`` — the LangGraph Debate Evaluator node factory.
"""

from __future__ import annotations

from tradingagents.debate.config import (
    DEFAULT_DEBATE_TERMINATION_CONFIG,
    DebateTerminationConfig,
    resolve_debate_termination_config,
)
from tradingagents.debate.conflicts import (
    build_conflict_summary,
    conflict_id_for,
    derive_conflicts,
)
from tradingagents.debate.evaluator import evaluate_round
from tradingagents.debate.evaluator_node import create_debate_evaluator_node
from tradingagents.debate.evidence_manifest import build_citation_allowlist
from tradingagents.debate.models import (
    BudgetState,
    ClaimEvidenceLink,
    ConflictAction,
    ConflictAssertion,
    ConflictKind,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    ConflictSummary,
    DebateRoute,
    DebateTurn,
    DecisionTraceEntry,
    MetadataParseStatus,
    RoundMetrics,
    RoutingDecision,
    Stance,
    StanceSnapshot,
    StopReason,
)
from tradingagents.debate.turn import (
    METADATA_INSTRUCTION,
    build_failed_turn,
    parse_turn_metadata,
)

__all__ = [
    "DEFAULT_DEBATE_TERMINATION_CONFIG",
    "DebateTerminationConfig",
    "resolve_debate_termination_config",
    "evaluate_round",
    "create_debate_evaluator_node",
    "build_citation_allowlist",
    "derive_conflicts",
    "build_conflict_summary",
    "conflict_id_for",
    "DebateTurn",
    "ConflictRecord",
    "ConflictAssertion",
    "ConflictSummary",
    "ConflictAction",
    "ClaimEvidenceLink",
    "StanceSnapshot",
    "RoundMetrics",
    "BudgetState",
    "RoutingDecision",
    "DecisionTraceEntry",
    "Stance",
    "ConflictKind",
    "ConflictSeverity",
    "ConflictStatus",
    "DebateRoute",
    "StopReason",
    "MetadataParseStatus",
    "parse_turn_metadata",
    "build_failed_turn",
    "METADATA_INSTRUCTION",
]
