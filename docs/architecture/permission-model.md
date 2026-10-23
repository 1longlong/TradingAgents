# Permission Model

This document defines what an automated actor (OpenCode, Codex, or any coding
agent) is and is not permitted to do in this repository. It is the prose
authority; the machine-readable form is `.opencode/permissions.jsonc`. It is
also enforced by mode/phase rules.

## Actor classes

| Actor | Purpose | Can run? |
| --- | --- | --- |
| Human (student) | Authority for all approvals and phase decisions | Always |
| Coding agent (OpenCode/Codex) | Read/analyze/implement within scope of the active phase | Only within phase scope |

## What agents MAY do (default, within phase scope)

- Read source, tests, and docs.
- Run offline deterministic tests, Ruff, and the doc/schema validators.
- Write source, tests, and docs to implement the active phase's requirements.
- Edit governance docs and the trace matrix to keep them consistent with a
  change.

## What agents may NOT do (denied by default)

- **Network / paid API.** No calling external data vendors, LLM providers, or
  paid endpoints unless the phase explicitly authorizes it.
- **Secrets.** No reading, printing, copying, committing, or transmitting API
  keys, tokens, or `Bearer`/`sk-` strings. Use `.env.example` placeholders only.
- **Commit / push / PR / release.** No `git commit`, `git push`, PR, or release
  without explicit human approval.
- **Revert / reformat / rewrite unrelated user code.** No mass reformat or
  out-of-scope edits.
- **Phase 4B / live-provider benchmarking.** No live-provider performance
  benchmark; Phase 4A offline comparison is approved but Phase 4B is not
  authorized and remains denied by default.
- **Production threshold tuning.** Not authorized without separate explicit
  human approval.
- **Unrequested features.** No unrequested feature work beyond the approved
  scope.

## Approval gates for privileged actions

| Action | Required before proceed |
| --- | --- |
| Run a network/integration test | Explicit phase authorization; mark `@pytest.mark.integration`. |
| Commit / push / PR | Explicit human statement ("commit", "push", "open a PR"). |
| Start a new phase | Recorded human review in `docs/review-memo.md`. |
| Introduce a new requirement | New stable ID + trace-matrix row in the same change. |

## Denied-action handling

When an agent's tool would perform a denied action (network, secret read,
commit, push), the agent MUST stop, explain, and ask the human for approval
instead of performing it. Fail closed on missing or ambiguous approval — the
default is to deny and ask.

## Model uncertainty (recorded)

The exact schema for `.opencode/permissions.jsonc` could not be fully verified
against the installed OpenCode version within this environment (no access to
external config). A conservative minimal documented form is used, and that
uncertainty is recorded in `docs/debt-register.md` and
`docs/architecture/risk-list.md`. Any supported key that is later verified may
be added in a follow-up, but no unsupported key is invented here.