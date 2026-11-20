# ADR-001 — Deterministic Data Quality Gate

- **Status:** Accepted
- **Date:** 2026-10-20 (Step 1/Step 2), graph integration 2026-10-21 (Phase 3A)
- **Deciders:** CS5351 project (student), with coding-agent and human review
- **Trace:** `FR-DQG-001`, `FR-DQG-002`, `FR-DQG-003`, `NFR-DET-001`, `NFR-FC-001`, `NFR-AUD-001`

## Context

The upstream `TradingAgents` framework opens a full-strength Bull/Bear debate
even when the verified market snapshot is incomplete, stale, or internally
inconsistent. A low-quality dataset could reach a strong (unrestricted) debate,
which is both a quality risk and a wasted-cost risk. We need a gate that runs
before the debate and can fail closed.

We also want the gate to be **deterministic** and **offline-testable**: it must
not depend on an LLM call or on the current clock for its verdict, so a test can
pin behavior.

## Decision

Introduce a pure, LLM-free Data Quality Gate. It operates on typed,
JSON-serializable records (`EvidenceRecord`, `SourceAttempt`,
`ValidationResult`, `EvidenceGroupQuality`, `GateDecision`) and validates the
verified market snapshot against five deterministic validation classes
(completeness, format, freshness, look-ahead, cross-source consistency).

- Verdict precedence is authoritative: **blocked > degraded > normal**.
- **Fail closed:** an empty input or any internal exception is turned into
  `blocked`, never `normal`.
- **Dependency-injectable:** the gate node accepts a snapshot builder, adapter,
  validator, aggregator, gate builder, run-id builder, and `decided_at`
  provider so tests substitute a fixed snapshot and a fixed clock.
- **Stable identifiers:** `run_id` derives from `(trade_date, normalized symbol)`
  so evidence IDs and gate output are identical for the same `(symbol, date)`.
- **Serialization:** only plain dicts/lists/strings are written into
  `AgentState`; `Decimal` serializes to a fixed-precision string; ordering is
  deterministic.

## Consequences (positive)

- Low-quality runs are blocked or degraded before debate, controlling quality
  and cost.
- Deterministic, offline, no LLM call; fully unit-testable.
- Fail-closed behavior prevents silent normal-on-error.

## Consequences (negative / trade-offs)

- Slightly more upfront validation work (five classes) before debate.
- The gate is conservative: `degraded` caps confidence, which may reject runs a
  human would tolerate. This is intentional (fail closed) but a real trade-off.
- New evidence model must stay acyclic (no nested `SourceAttempt` in
  `EvidenceRecord`, no back-reference cycle) — enforced by invariant.

## Alternatives considered

See `docs/architecture/option-ledger.md` (LLM-based gate vs. deterministic gate;
embedding `SourceAttempt` vs. separate record; float vs. Decimal).

## Related

- `docs/architecture/invariants.md`
- `docs/architecture/trace-matrix.md`
- `docs/code-governance/structural-constraints.md`