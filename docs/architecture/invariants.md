# System Invariants (non-negotiable)

These invariants constrain every change to the CS5351 feature work. A change
that violates one is not acceptable, even if it makes a test pass. Each
invariant is traced to requirements in `docs/architecture/trace-matrix.md`.

## INV-1 Fail closed on missing evidence or internal error

The Data Quality Gate must never return `normal` when evidence is missing or an
exception is raised during gate construction; it returns `blocked`. The Debate
Evaluator must route to `summarize`/`insufficient_evidence` on an internal
failure, never continue.

## INV-2 Determinism of the gate and evaluator

The evidence gate and the debate evaluator are pure and LLM-free. Identical
inputs produce identical outputs regardless of insertion order, clock, or
environment. The only injected time is a validated ISO-8601 `decided_at`.

## INV-3 Point-in-time integrity (no look-ahead)

No future data reaches a decision. Every dated path (market, news, macro,
social, memory) is evaluated "as of" the requested trade date. This is an
upstream invariant the project preserves, not introduces.

## INV-4 Acyclic, JSON-safe serialization

`EvidenceRecord` carries exactly the locked 20 fields; `SourceAttempt` is a
separate 7-field record and is never embedded in `EvidenceRecord`;
`ValidationResult` references its owning record by `evidence_id` string only.
Serialization is acyclic and JSON-safe.

## INV-5 Stable, deterministic identifiers

`run_id` (and therefore evidence IDs) derive from `(trade_date, normalized
symbol)`, never from a random value.

## INV-6 Auditability of every decision

Gate verdicts carry stable reason codes, policy version, critical evidence IDs,
and a human-readable reason. Debate decisions emit an explicit decision trace.

## INV-7 Budget safety

The debate always reserves summary tokens/time before deciding to continue, and
enforces hard max tokens/time/calls, so a run cannot exhaust budget mid-debate
without producing a report.

## INV-8 Backward compatibility

New config groups default to safe values and preserve existing routing when
disabled. The default `pytest -q` run and the default runtime behavior must not
regress.

## INV-9 Offline, deterministic testing

No unit test requires network or a paid LLM. Vendor/live tests are
`@pytest.mark.integration` and opt-in; default `pytest -q` is offline.

## INV-10 Secret safety

No API key, token, or `Bearer`/`sk-` string appears in committed files. Secrets
stay in environment variables or gitignored `.env`.

## INV-11 English-only governance text

Prompts, commit messages, review comments, and code comments are in English.

## INV-12 No unapproved persistence of user changes

Agents do not revert, reformat, or rewrite unrelated user-authored code, and do
not commit/push/PR or start Phase 4 without explicit human approval.

## INV-13 Conflict lifecycle safety

A `ConflictRecord` is derived **only** from the structured `conflict_assertions`
a `DebateTurn` carries (parsed from `DEBATE_METADATA`). A conflict is never
fabricated from prose or chain-of-thought; a turn with no assertions contributes
no conflict. Conflict IDs are deterministic from `(normalized topic, kind)`
(INV-5). Every cited evidence ID must be known, High/Medium, and observed on or
before the target date (INV-3); an unknown/low/future ID never creates a
conflict and a re-observation with such an ID drops the previously-open conflict
(fail closed, INV-1). Action-only disagreement is tracked but never blocks
debate termination. Resolution/escalation is a no-op on a non-open conflict and
records exactly one human-readable reason.