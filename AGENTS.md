# AGENTS.md — Coding-Agent Governance

This file governs every coding agent (human, OpenCode, Codex, or any other AI
assistant) that edits this repository. It is the first document an agent must
read before making any change, per the static startup prompt
(`Prompt.md` and `prompts/prompt_v1.2.yaml`).

## 1. Read the repository instructions first

- Read `AGENTS.md`, `architecture-blueprint.md`, `docs/architecture/invariants.md`,
  and `docs/architecture/trace-matrix.md` before editing source or tests.
- Read `pyproject.toml` for the toolchain (Ruff, pytest markers) and the
  `tests/` conventions in `conftest.py` before adding or changing tests.

## 2. Language

- All prompts, commit messages, review comments, and code comments MUST be in
  **English**. Non-English text is only permitted where it is itself the object
  of study (e.g. localization fixtures/translations), never for agent
  instructions or documentation narrative.

## 3. Preserve user changes

- Do **not** revert, reformat, or rewrite unrelated user-authored code.
- Do **not** mass-reformat files not touched by the task. Ruff formatting
  adoption is intentionally deferred (see `pyproject.toml`).
- If a change is required for the task, keep the diff as small as possible and
  clearly scoped.

## 4. No secrets

- Never read, print, copy, commit, or transmit API keys, tokens, or
  `Bearer`/`sk-` strings. If a `.env` file is needed, use `.env.example`
  placeholders only.
- Never write a real secret into any committed file. Real secrets stay in
  environment variables or `.env` (gitignored).
- Scan new files for secrets before finishing (see
  `docs/code-governance/verification-constraints.md`).

## 5. No network or paid API without authorization

- Offline, deterministic, LLM-free execution is the default. Do not call
  external data vendors, LLM providers, or paid APIs unless the task
  explicitly authorizes it.
- Tests that require external services MUST be marked `@pytest.mark.integration`
  and are opt-in (see `test/live/README.md`). The default `pytest -q` run must
  not require network access.

## 6. No commit / push / PR without explicit approval

- Never `git commit`, `git push`, open a PR, or create a release unless the
  human explicitly and unambiguously asks for it.
- The default is to leave all work as uncommitted working-tree changes.

## 7. Use offline deterministic tests

- Run the offline deterministic suite before finishing a change: this is the
  project's verification of record (see `docs/architecture/evaluation-logbook.md`).
- Do not claim a green full suite when known date-sensitive cache failures or a
  network-reachability-sensitive baseline failure remain. Record exact outcomes
  with the commands that produce them.

## 8. Maintain traceability

- Every new or changed requirement must be mapped in
  `docs/architecture/trace-matrix.md` to its design artifacts, source files, and
  tests.
- Assign and re-use stable requirement IDs (`FR-DQG-*`, `FR-DDT-*`, `NFR-*`).
- Update the trace matrix in the same change that adds the requirement.

## 9. Record AI use and reviews

- Record each AI-tool use and each human review in `docs/ai-use-log.yaml` and
  `docs/review-memo.md`. Note tool, scope, date, and outcome; never copy secrets.
- At phase boundaries, record a human review decision.

## 10. Fail closed on missing evidence

- If evidence, a decision, a requirement ID, or a verification result is
  missing or unknown, do **not** invent it. Mark it `TODO` with an owner and an
  action, and record it in `docs/debt-register.md` and `docs/architecture/risk-list.md`.

## 11. Human review at phase boundaries

- Each project phase (analysis, contract, implementation, verification) requires
  an explicit human review before proceeding. Record the outcome in
  `docs/review-memo.md`. Without a recorded review, do not claim a phase
  complete.

## 12. Scope discipline

- This is a documentation/governance scaffold plus the Phase 1–3B feature work
  and the Phase 4A deterministic offline baseline comparison. Phase 4A is
  completed and human-approved with limitations (WANG Yiwen 60536848,
  2026-10-23); only in-scope Phase 4A maintenance may proceed without further
  authorization.
- **Phase 4B** (live-provider benchmarking), **production threshold tuning**, and
  **unrequested features** remain prohibited without a separate explicit human
  authorization.
- Do **not** revert approved work, add features not requested, duplicate or
  relocate source trees, or invent team decisions/approvals.