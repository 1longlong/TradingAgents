# TradingAgents Static Startup Instruction

Read the repository-root `AGENTS.md`, then follow its reading order for requirements, architecture, governance, and relevant source code. That file is the governance entry point. This file is the static launch instruction, not the requirements registry or a runtime prompt.

## 1. Establish facts and gaps

- Extend TradingAgents v0.5.0 from `release`. Source is under `src/`; tests are under `test/offline/` and `test/live/`.
- Do not replace the existing system or infer requirements from historical demonstrations or missing documents. Do not preselect web frameworks, frontend frameworks, storage, or new module names.
- Inspect existing workspace changes and preserve user content. Identify the current authorization and valid approvals.
- List relevant missing or empty requirements, blueprints, ADRs, invariants, permissions, and traceability records. Complete and obtain human confirmation of missing implementation prerequisites before relying on them. Empty files are not approvals.
- Read-only inspection and explicitly authorized documentation may continue. Do not implement product code under the guise of preparation.
- Empty requirements/architecture files do not block requirements discovery. Discuss in Plan, persist agreed drafts in Docs, and approve implementation only after the required artifacts and tests exist.

## 2. Present an execution plan and wait for approval

Present the plan in the current conversation and preserve traceable references in the existing `docs/review-memo.md` or corresponding `transcripts/` record. Include:

1. Requirement IDs, sources, acceptance criteria, and explicit exclusions for this iteration.
2. Mappings from requirements to architecture elements, source paths, test nodes, and runtime monitors. Identify safety-critical changes.
3. Interface contracts: inputs, outputs, state, errors, cancellation and recovery, resource ownership, version compatibility, and deterministic boundaries.
4. An explicit modification allowlist, proposed dependencies and rationale, and any required ADRs or additional permissions.
5. A prior test plan and concrete cases, including at least one negative case per feature, violation cases for affected invariants, and previous-suite regression commands.
6. Implementation steps, failure handling, verification evidence, and human checkpoints.

**Do not generate product implementation code before the plan and test strategy receive explicit human approval.** Associate approval with a plan/test version or verifiable content and its approval time. If test files are written first, complete their human review before product implementation starts. Honor explicit authorization already given in the current conversation rather than asking again for the same scope.

## 3. Build within the approved scope

- Enter the Build role only after approval. Implement the smallest increment in dependency order.
- Reuse existing Python packages, business validation, and public interfaces. Preserve CLI and Python API compatibility.
- Implement only approved modules and interfaces. If requirements, permissions, safety boundaries, or architecture change, submit the necessary revision before continuing dependent implementation.
- Do not weaken tests, thresholds, or safety checks to obtain a passing result.
- At build completion, report actual changes, deviations, and the proposed verification scope. Retain a human build checkpoint.

## 4. Self-verify and obtain independent review

Apply structural, regression, and behavioral verification from `docs/code-governance/verification-constraints.md`. For real API tests, confirm existing authorization, credential readiness, and cost limits. Report missing conditions as unrun or skipped checks, never as passing checks.

The verification role must not modify implementation or weaken tests. Return findings to Build for repair and re-verification. One tool may assume roles in separate phases; do not automatically launch subagents.

Submit the change list, verification commands and results, unresolved failures, requirement traceability, AI-use records, and session records for human review. Only humans issue human review decisions. An agent may recommend a verdict but cannot record its own recommendation as human `APPROVE`.

## 5. Close the iteration

Check that requirements, architecture, rules, tests, and process records have evolved together. Identify unfinished work and release blockers. Do not automatically commit, push, merge, or publish. Perform subsequent actions only when the current human has explicitly authorized them.


## Imported core prompt lineage

The release prompt versions `prompts/prompt_v1.2.yaml` and
`prompts/prompt_v1.3.yaml` are retained as core governance history. Their
plan/test approval, safety, offline verification and human-review intent remains
applicable. Their former root-level source layout is superseded by this
branch's already-established `src/` and `test/` paths. Do not treat historical
phase approvals or a prompt version as authorization for new product work.
