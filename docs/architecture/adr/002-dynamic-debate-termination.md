# ADR-002 — Dynamic, Evidence-Aware Debate Termination

- **Status:** Accepted
- **Date:** 2026-10-21 (Phase 3B)
- **Deciders:** CS5351 project (student), with coding-agent and human review
- **Trace:** `FR-DDT-001`, `FR-DDT-002`, `FR-DDT-003`, `FR-DDT-004`, `FR-DDT-005`, `NFR-BUD-001`, `NFR-BC-001`, `NFR-DET-001`, `NFR-FC-001`, `NFR-AUD-001`

## Context

The upstream debate always runs a fixed `max_debate_rounds`. This is wasteful
when the Bull and Bear have already converged or when neither is producing new
evidence, and it is unsafe when budget is running low because no reserve is
guaranteed for the eventual summary. The project needs a dynamic, evidence-aware
termination rule.

The decision rule must be **deterministic** and **offline-testable** and must
fail closed on error: an internal problem must never cause the debate to keep
running (cost) or to stop without producing a report.

## Decision

Introduce a pure `DebateEvaluator` (`evaluate_round`) plus a LangGraph
`evaluator_node` that runs after each completed Bull + Bear round and applies
the authoritative rule ordering:

1. Critical evidence/gate Blocked -> `stop` / `insufficient_evidence`.
2. Summary reserve cannot be guaranteed, or a token/time/call hard limit is
   reached -> `summarize` / `budget_exhausted`.
3. `max_debate_rounds` reached -> `summarize` / `max_rounds_reached`.
4. Both sides produced zero new valid evidence for the round (respecting
   `no_new_evidence_patience`) -> `summarize` / `no_new_evidence`.
5. No critical/major open conflict and stances are close -> `summarize` /
   `consensus_reached`.
6. New High/Medium evidence exists, a critical/major conflict remains, and
   budget permits -> `continue` / `continue_for_new_evidence`.
7. A critical/major interpretive conflict remains, there is material stance
   change, and budget permits -> `continue` / `continue_for_material_change`.
8. Otherwise -> `summarize` / `diminishing_returns`.

Supporting decisions:

- **Evidence manifest / citation allowlist:** debate turns may only cite
  evidence IDs allowed by the gate manifest; a turn with no valid new evidence
  (respecting patience) ends the debate. A metadata parse failure never extends
  the debate.
- **Budget reserve:** summary tokens/time are reserved before deciding to
  continue; hard max tokens/time/calls are enforced; an explicit decision trace
  is emitted for audit.
- **Backward compatibility:** a `debate_termination` config group is added with
  validated safe defaults; `enabled=False` reproduces the legacy fixed-round
  routing.
- **ConflictRecord runtime lifecycle (`FR-DDT-005`):** a pure, LLM-free tracker
  (`tradingagents/debate/conflicts.py`) creates, observes (deduplicates/merges),
  resolves, and escalates `ConflictRecord` objects, deriving conflicts **only**
  from the structured `conflict_assertions` a `DebateTurn` carries (parsed by
  `turn.py` from `DEBATE_METADATA`). Conflict IDs are deterministic SHA-1
  digests of `(normalized topic, kind)` (INV-5). Evidence validation fails
  closed (INV-1/INV-3): an assertion citing an unknown, Low, or future evidence
  ID never creates a conflict, and a re-observation citing such an ID drops the
  previously-open conflict. Empty evidence on a new factual/interpretive
  conflict does not create it; a turn with no assertions contributes no
  conflict. Action-only disagreement is tracked (so the Research Manager can
  weigh it) but excluded from `blocks_termination`. A `resolve`/`escalate`
  assertion closes or promotes an open conflict and records the human-readable
  reason; resolving a non-open conflict is a no-op (no second misleading
  reason). The evaluator node persists the derived conflicts and a safe,
  structured, prose-free `ConflictSummary` (with resolution notes and an
  authoritative open-blocking count) to debate state, and the Research Manager
  injects that summary safely.

## Consequences (positive)

- Reduces wasted turns and cost while guaranteeing a report.
- Deterministic and offline-testable; decision trace is auditable.
- Configurable and backward-compatible.

## Consequences (negative / trade-offs)

- The dynamic rules are more complex than a fixed round count, so the decision
  ordering must be carefully tested (rule precedence is subtle).
- The `DEBATE_METADATA` append instruction adds a machine-parseable marker to
  the researcher output; a marker-absent fallback heuristic is needed, which is
  a small surface of imperfection (mitigated: a parse failure contributes zero
  new evidence and can never extend the debate).
- The conflict tracker adds another structured-marker surface (`conflict_a`);
  a malformed assertion contributes no conflict (fail closed), and the
  evidence-validation plus dedup/merge rules must be carefully ordered (INV-13).

## Alternatives considered

See `docs/architecture/option-ledger.md` (fixed rounds vs. dynamic; LLM-judged
termination vs. deterministic; prose-only turn metadata vs. structured marker).

## Related

- `docs/architecture/invariants.md`
- `docs/architecture/runtime-policy-catalog.md`
- `docs/architecture/trace-matrix.md`