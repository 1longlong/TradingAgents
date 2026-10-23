"""Phase 4A — deterministic offline baseline-comparison infrastructure.

This package implements a pure, LLM-free, deterministic comparison model/runner
that contrasts a *fixed-round baseline* with the *dynamic* debate-termination
policy on identical case identity ``(ticker, target_date, evidence_snapshot_id,
policy_version)`` and identical scripted debate inputs.

Guarantees (Phase 4A scope):

- **Offline & deterministic**: no LLM call, no data vendor, no network. Both
  strategies consume the exact same scripted case identity and evidence
  snapshot; a mismatch fails closed (``PairingError``), never silently
  compared.
- **Measured vs estimated separated**: wall-clock/token values reported by a
  provider are *measured*; determinants such as char-based token/time
  estimates are *estimated*. Tests never depend on timing.
- **Machine-readable metrics**: evidence-citation coverage is derived from
  valid cited evidence IDs; false-strong-conclusion rate is computed from an
  explicit ``strong_conclusion`` flag plus the gate/quality outcome, never
  inferred from prose; human traceability uses a documented rubric and stays
  pending/unscored when no human score is supplied.
- **Zero-denominator safety**: every ratio has an explicit denominator and a
  documented zero-denominator behavior (returns ``None`` rather than raising or
  fabricating).

Modules:
- ``schemas`` — typed, validated result/aggregate records with stable JSON.
- ``metric_formulas`` — the explicit metric formulas.
- ``runner`` — pairing, aggregation, fail-closed replay.
- ``report`` — deterministic JSON + Markdown writers.
- ``fixtures`` — representative scripted case results (scenarios D/E/F).
"""

from __future__ import annotations

from tradingagents.comparison.schemas import (
    CaseAggregate,
    CaseIdentity,
    CaseResult,
    ComparisonReport,
    StrategyKey,
)

__all__ = [
    "CaseIdentity",
    "CaseResult",
    "CaseAggregate",
    "ComparisonReport",
    "StrategyKey",
]
