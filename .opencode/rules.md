# .opencode/rules.md

Human-only file. The coding agent must not modify this file.

## Always-On Rules

- Read AGENTS.md before any task.
- Default read: false. Default write: false.
- Only access paths explicitly whitelisted in .opencode/permissions.jsonc.
- Never modify frozen paths or src/safety/** without human approval and an architecture decision.
- Produce an execution plan before writing any code.
- Stop and wait for human approval after producing the plan.
- Implement one step at a time. Stop after each step for human review.
- Every new feature must have at least one negative test.
- Every invariant must have at least one test that fails when the invariant is violated.
- Update docs/ai-use-log.yaml whenever code or prompts change.
- If a requirement is ambiguous, ask the human instead of assuming.
- If a test fails, report it. Do not skip, delete, or weaken tests.
