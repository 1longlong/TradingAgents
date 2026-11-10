# Proposed Text for `.opencode/rules.md` — AWAITING WANG YIWEN MANUAL ADOPTION

> **Status:** PROPOSAL ONLY. `.opencode/rules.md` is **HUMAN-ONLY** under the
> course specification and is **NOT edited by any agent**. This file records
> proposed human text for the human owner (WANG Yiwen, 60536848) to adopt
> **manually** if desired. It is not active and confers no authority until the
> human copies it into `.opencode/rules.md` themselves. The existing
> `.opencode/rules.md` remains in force unchanged.

The current `.opencode/rules.md` has 12 binding rules. The proposal below adds
three operational clarifications that the 2026-11-06 compliance audit called
for. Nothing here loosens an existing rule.

## Proposed additions (human to adopt or reject)

### Proposed rule 13 — Plan-first, stop-before-code

> Before generating or editing any feature code or tests, output a traceable
> execution plan covering scope, interfaces, tests, steps, and risks, then
> **STOP** and wait for explicit human approval. The test plan and test cases
> must be human-approved before implementation. A change to scope, safety
> semantics, or the plan requires reapproval. Human decisions cannot be inferred
> or authored by the agent.

### Proposed rule 14 — Role scope and frozen areas

> Operate only within the single role and path scope granted for the task
> (Planner/Builder/Verifier). Human-only and frozen areas — `.opencode/rules.md`,
> `.opencode/permissions.jsonc`, `.github/**`, dependency files, secrets, and
> paths outside the repository — are never edited by an agent; the agent
> proposes and the human applies.

### Proposed rule 15 — Safety-critical changes need ADR + approval

> A change to gate/evaluator/output-guard/fail-closed/budget/permission/prompt
> behavior requires an ADR and explicit human approval before merge. Context and
> rules freshness is re-checked each sprint (or when the governing prompt version
> or `AGENTS.md` changes); a stale context requires re-reading before any edit.

## Rationale (for the human reviewer)

- Rule 13 closes the audit's D9 gap (no explicit plan-first STOP before code).
- Rule 14 makes the deny-by-default role/path intent explicit in agent-facing rules.
- Rule 15 ties safety changes to ADR + human approval and adds a freshness check.

## Note on the current `.opencode/rules.md` (not edited by the agent)

The current `.opencode/rules.md` still references `prompts/prompt_v1.2.yaml` and
does not contain the plan-first STOP rule. Because that file is HUMAN-ONLY, the
agent does not update it. If the human adopts this proposal, they should also
advance the referenced prompt version to `prompts/prompt_v1.3.yaml`. Until the
human edits it, this inconsistency is recorded as pending human adoption, not
silently fixed.

## What the agent will NOT do

- It will not write these into `.opencode/rules.md`.
- It will not claim `.opencode/rules.md` already contains them.
- It will not mark them adopted without a human action and a recorded decision.
