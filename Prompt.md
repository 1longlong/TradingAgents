# Prompt.md

You are the coding agent for this repository.

Start by reading AGENTS.md, then read the architecture and governance files in the order specified there.
Some files in the read order are stubs marked "To be produced by the execution plan". Treat them as outputs you must produce later, not as existing inputs.

Your task is to design and implement a simulated trading subsystem on top of TradingAgents.

The subsystem must:
- Accept LLM trading decisions as advisory input.
- Pass every decision through a deterministic safety rule engine.
- Execute only APPROVED decisions in a simulator.
- Update simulated positions and cash.
- Write an append-only audit log.
- Support human-in-the-loop approval when safety rules trigger.

Before writing any code, produce an execution plan that includes:
1. Traceability: each requirement ID mapped to a module and a test.
2. Interface contracts: function and class signatures, inputs, outputs, and error behavior.
3. Scope boundaries: files to create, files to modify, and files that must not be touched.
4. Testing strategy: offline tests, live tests, negative tests, and invariant tests.
5. Step-by-step implementation plan.

Output the plan and stop.
Do not write code until a human approves the plan.

After approval:
- Implement one step at a time.
- Stop after each step and wait for human review.
- Do not run the entire project unattended.
- All code must comply with docs/code-governance/verification-constraints.md and .opencode/permissions.jsonc.

If you need to modify a frozen path or a safety-critical file, stop and request an architecture decision.

Update docs/ai-use-log.yaml whenever you change code or prompts.
