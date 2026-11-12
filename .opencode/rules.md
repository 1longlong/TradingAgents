# OpenCode Agent Rules (project-local)

These rules bind OpenCode while working in this repository. They are enforced by
the static startup prompt (`Prompt.md`, `prompts/prompt_v1.2.yaml`) and by
`.opencode/permissions.jsonc`. Read `AGENTS.md` first.

## 1. Read the repository instructions first

Before editing any source or test, read `AGENTS.md`, `architecture-blueprint.md`,
`docs/architecture/invariants.md`, and `docs/architecture/trace-matrix.md`, plus
`pyproject.toml` and `tests/conftest.py`.

## 2. English only

All prompts, commit messages, review comments, and code comments are in English.

## 3. Preserve user changes

Do not revert, reformat, or rewrite unrelated user-authored code. Do not
mass-reformat files not touched by the task. Keep diffs minimal and scoped.

## 4. No secrets

Never read, print, copy, commit, or transmit API keys, tokens, or
`Bearer`/`sk-` strings. Use `.env.example` placeholders only. Scan new files for
secrets before finishing.

## 5. No network or paid API without authorization

Offline, deterministic, LLM-free execution is the default. Do not call external
data vendors, LLM providers, or paid APIs unless the task explicitly authorizes
it. Tests requiring external services are `@pytest.mark.integration` and opt-in;
the default `pytest -q` is offline.

## 6. No commit / push / PR without explicit approval

Never commit, push, open a PR, or create a release unless the human explicitly
asks. Default: leave work as uncommitted working-tree changes.

## 7. Use offline deterministic tests

Run the offline deterministic suite before finishing. Do not claim a green full
suite when known date-sensitive cache failures or a network-reachability
baseline failure remain. Record exact outcomes in
`docs/architecture/evaluation-logbook.md`.

## 8. Maintain traceability

Map every new/changed requirement in `docs/architecture/trace-matrix.md` with a
stable ID (`FR-DQG-*`, `FR-DDT-*`, `NFR-*`) in the same change.

## 9. Record AI use and reviews

Update `docs/ai-use-log.yaml` and `docs/review-memo.md`. Never copy secrets.

## 10. Fail closed on missing evidence

Never invent evidence, a decision, a requirement ID, or a verification result.
Mark unknown items `TODO` with an owner/action and record in
`docs/debt-register.md` and `docs/architecture/risk-list.md`.

## 11. Human review at phase boundaries

Each phase (analysis, contract, implementation, verification) requires an
explicit recorded human review in `docs/review-memo.md` before proceeding.

## 12. Scope discipline

Phase 4A (deterministic offline baseline comparison) is completed and
human-approved with limitations (WANG Yiwen 60536848, 2026-10-23); only
in-scope Phase 4A maintenance may proceed without further authorization. Phase
4B (live-provider benchmarking), production threshold tuning, and unrequested
features remain prohibited without separate explicit human authorization. Do
not add unrequested features or duplicate/relocate source trees.