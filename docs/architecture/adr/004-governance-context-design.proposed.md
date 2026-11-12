# ADR-004 (PROPOSED) — Governance Context Assembly and Compaction Design

**Status:** PROPOSED — design only. **Not implemented, not enforced, and not
approved.** This ADR does not rewrite any historical human approval. Nothing in
this document asserts that the described runtime behavior currently exists; see
the "Implementation status" section.

**Date:** 2026-11-06. **Author:** AI-assisted documentation (OpenCode), for
human review. **Decision owner:** WANG Yiwen (human) — approval pending.

## Context

Coding agents (OpenCode/Codex/others) operate under a course-governance scaffold
(`AGENTS.md`, `Prompt.md`, `prompts/`, `docs/architecture/*`). The scaffold
records rules, invariants, requirement and trace data, live evidence, review
history, and the working session's task plan. Today these are prose documents
that a human or an agent reads; there is **no deterministic context-assembly,
budgeting, or compaction code** in this repository. The project's own output-token
caps (`max_tokens`, `reserved_summary_tokens`) govern model output, not the
school-context window. The audit (2026-11-06) flagged that a real layered-context
design with compaction thresholds and provenance-preserving summaries is missing.

This ADR proposes that design. It is deliberately a **proposal**: implementing it
would be a later, separately authorized feature change.

## Decision (proposed)

Adopt a layered, deterministic context assembly model with an explicit budget and
a provenance-preserving compaction pipeline.

### Authority sources (distinct; not conflated)

Not all text in the window has the same authority. The design must keep these
**separate** and must not let a lower-authority source override a higher one:

- **(S) Actual system / developer safety instructions** — the real platform-level
  system/developer message that governs the agent runtime. This is the highest
  authority. It is *not* repository text and cannot be produced by the agent from
  repository files.
- **(P) Project standing constraints** — repository `AGENTS.md`, `.agent/rules.md`,
  `docs/architecture/invariants.md`, ADRs, and `prompts/prompt_v*.yaml`. These are
  **standing project constraints, not an immutable system authority**. They bind
  work on this project, but they are data read from the repository; they do not
  acquire system-level authority merely by being on disk, and a repository file
  cannot grant itself the power to override the platform system/developer safety
  instructions.
- **(H) Human governance decisions** — human-authored approvals/scope in
  `docs/review-memo.md` and recorded human statements. Authoritative for scope and
  approvals; never authored or inferred by the agent.
- **(U) Untrusted retrieved / tool content** — file contents fetched by tools,
  logs, web/doc retrieval, model output. This is **untrusted evidence**: it may
  inform, but it can never authorize an override, a permission grant, or a
  scope change. Instructions that appear *inside* tool/retrieved content are
  treated as data, not commands.

The safety constraints the design must protect are principally (S); the project
constraints (P) and invariants restate and operationalize them for this repo.

### Context layers (deterministic order 1..6; highest retained authority first)

1. **Platform system/developer safety layer (S)** — the real runtime system /
   developer safety instructions. Never compacted, never summarized, never
   dropped; not sourced from repository files.
2. **Human governance layer (H)** — human-approved decisions and scope:
   `docs/review-memo.md` decisions, approved Phase 4A limitations, active scope
   authorization. Human-authored; the agent may read, never author.
3. **Stable project-constraint layer (P, stable part)** — `AGENTS.md` safety
   rules, invariants `INV-1..INV-13` (safety-critical ones), secret/network/
   commit/plan-first rules, ADRs, requirement `fit_criteria`. Standing project
   constraints; changes require a human-governed decision.
4. **Task plan layer (P, active)** — the current traceable execution plan and its
   approval state (see `prompts/prompt_v1.3.yaml`). Must precede any code/test
   edit.
5. **Working evidence layer (U, volatile)** — current test outputs, logs, file
   excerpts, in-progress diffs. The most volatile layer; treated as untrusted
   evidence; first to be compacted.
6. **History / transcript layer (U, provenance-summarized)** — prior session
   chronology, `ai-use-log.yaml`, logbook. Summarized with provenance, never
   silently rewritten.

### Deterministic assembly

- Assembly order is fixed: layers are assembled top-to-bottom **1 → 6**, then the
  **critical project constraints from layer 3 (plus the layer-1 safety text) are
  repeated verbatim at the end** of the rendered prompt as a recency re-injection.
  Ordering is thus deterministic and non-contradictory: the full order is
  `[1,2,3,4,5,6]` followed by `[repeat: 1 and 3 critical constraints]`, and the
  repeated block is an exact copy, never a paraphrase.
- Assembly is a pure function of the on-disk artifacts plus the task plan; no
  wall-clock or RNG dependency (mirrors INV-2), so a given input state assembles
  identically.
- Every assembled block carries a **provenance header** (source path, version or
  hash, layer id / authority tag S|P|H|U, freshness stamp).
- **Authority check:** a candidate line found in (U) that asserts a permission,
  override, or scope change is rejected; it cannot raise its own authority to S/P/H.

### Budget (design budget = 131072 tokens)

- The school-context design budget is **131072 tokens** total. It is a design
  budget, **not** a verified model limit; the actual model/gateway context limit
  remains unverified and must be probed before any implementation is trusted.
- Reserved (never used for working evidence):
  - Immutable safety layer: always retained in full (counted, not truncated).
  - Critical-constraint re-injection reserve: retained verbatim.
  - Compaction summary reserve: enough to hold the provenance summaries.

### Compaction thresholds and reserve (PROPOSED, not tuned)

These are proposals to be validated, **not** production thresholds:

| Parameter | Proposed value | What is counted | Rationale |
| --- | --- | --- | --- |
| Soft compaction trigger | 70% of 131072 ≈ 91750 tokens | assembled prompt tokens | leave headroom for tool output |
| Hard compaction trigger | 85% of 131072 ≈ 111411 tokens | assembled prompt tokens | force compaction before overflow |
| Compaction summary reserve | 8,192 tokens | summary output budget | bounded summary |
| Critical-constraint reserve | counted from verbatim layer | safety+governance text | never dropped |

Token counting method is **unverified**: no tokenizer is wired. A deterministic
character-based estimator could be used as a fallback but must be labelled
estimated (mirrors the existing `NFR-CMP-002` measured-vs-estimated rule).

### Keep / drop rules (PROPOSED)

- **Keep verbatim:** layer 1 (all), layer 2 decisions (all), layer 3 safety
  invariants and `fit_criterion`s of in-scope requirements.
- **Summarize with provenance:** layer 5 tool outputs and logs older than the
  current task step; layer 6 history. Summaries are structured (see schema) and
  must cite the source artifact and hash.
- **Drop only with a tombstone:** anything dropped gets a tombstone record
  (id, layer, reason, hash) so nothing disappears silently.
- **Never summarize/drop:** secrets are never in context; human decisions are
  never paraphrased into agent-authored text.

### Provenance-preserving summary schema (PROPOSED)

```yaml
summary:
  layer: "working-evidence"       # one of the six layers
  sources:                        # every summarized origin
    - path: "docs/architecture/evaluation-logbook.md"
      sha256: "<hash>"
      range: "entries 058-067"
  statements:
    - text: "strict offline suite 4 failed / 1661 passed (known baselines)"
      provenance: ["evaluation-logbook.md#067"]
      confidence: "verbatim-derived"   # or "inferred"
  tombstones:                     # dropped items
    - id: "tool-output-12"
      reason: "superseded by #067"
      sha256: "<hash>"
  reinjected_constraints: true    # critical constraints re-injected after this summary
```

A statement lacking provenance is rejected (fail closed).

### Critical-constraint re-injection

After any compaction, and after any session restart/version change, the immutable
safety layer and the active plan approval state are re-injected verbatim and the
assembly aborts if they cannot be re-read.

### Interruption / session / version freshness

- A session is marked **stale** if the governing prompt version
  (`prompts/prompt_v*.yaml` current marker), `AGENTS.md` hash, or the active plan
  approval id changed since it started.
- A stale session must re-read the immutable layer and re-confirm the plan before
  any further edit.
- Failure to establish freshness → **stop and ask the human** (fail closed).

### Failure fallback

- Assembly error, freshness failure, missing approval, or budget overflow with no
  compaction option → **stop before generating or editing** and ask the human.
- Never silently degrade to an unbounded or unprovenanced context.

## Alternatives considered

1. **Status quo (prose docs, human/agent reads manually).** Simple; but no budget,
   no compaction, no freshness guarantee — the audit's core gap. Rejected for the
   target design.
2. **Truncate oldest-first when over budget.** Cheap; but silently drops human
   decisions and safety text. Rejected: violates provenance and fail-closed.
3. **LLM-summarize the whole history each turn.** Flexible; but non-deterministic,
   costly, and can paraphrase human decisions (fabrication risk). Rejected.
4. **Layered + deterministic + provenance-preserving compaction (this proposal).**
   Auditable, reproducible, safety-preserving; more engineering effort.
   **Selected** for future implementation.

## Consequences

- Positive: deterministic, auditable, safety constraints survive compaction;
  freshness is explicit; human decisions cannot be paraphrased by an agent.
- Negative: requires a tokenizer/estimator decision, a schema, and tests that do
  not exist yet; adds assembly latency; the 131072 figure and thresholds are
  unvalidated.
- Neutral: no runtime behavior changes until implemented and human-approved.

## Reopen triggers

- The model/gateway context limit is measured and differs materially from 131072.
- A human decision is shown to be lost or paraphrased across a compaction.
- Token-estimation error is shown to cause premature or late compaction in a
  verified run.
- A future course requirement specifies a different context policy.

## Implementation status (honest)

- **Not implemented.** No context-assembly, budgeting, or compaction code exists
  in this repository (`tradingagents/`, `cli/`). The parameters and schema above
  are design proposals.
- **Not enforced.** No test asserts this behavior; none is claimed.
- **Not approved.** This ADR awaits explicit human review; it is not a decision
  of record.
- The live 2026-11-06 run's `budget_exhausted` finding is about *debate* budget
  accounting (`DEBT-021`), not this context budget; they are distinct concerns.
