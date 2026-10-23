# Coding-Agent Rules (shared, applied by any agent incl. OpenCode and Codex)

These rules apply to any coding agent working in this repository. They are the
operational form of `AGENTS.md`. Read `AGENTS.md` for the full authoritative
text before editing source or tests.

## Binding rules

1. **Read repository instructions first** — `AGENTS.md`,
   `architecture-blueprint.md`, `docs/architecture/invariants.md`,
   `docs/architecture/trace-matrix.md`, `pyproject.toml`, `tests/conftest.py`.
2. **English only** for prompts, commits, review comments, and code comments.
3. **Preserve user changes** — do not revert, reformat, or rewrite unrelated
   user-authored code; keep diffs minimal and scoped.
4. **No secrets** — never read, print, copy, commit, or transmit API keys,
   tokens, or `Bearer`/`sk-` strings. Use `.env.example` placeholders only.
5. **No network or paid API without authorization** — offline, deterministic,
   LLM-free execution is the default; external-service tests are
   `@pytest.mark.integration` and opt-in.
6. **No commit / push / PR without explicit approval** — default is uncommitted
   working-tree changes.
7. **Use offline deterministic tests** — run them before finishing; record exact
   outcomes and do not claim a green suite when date-sensitive/network-reachability
   failures remain.
8. **Maintain traceability** — map every new/changed requirement in
   `docs/architecture/trace-matrix.md` with a stable ID in the same change.
9. **Record AI use and reviews** — update `docs/ai-use-log.yaml` and
   `docs/review-memo.md`; never copy secrets.
10. **Fail closed on missing evidence** — mark unknown items `TODO` with an
    owner/action; record in `docs/debt-register.md` and
    `docs/architecture/risk-list.md`.
11. **Human review at phase boundaries** — each phase requires an explicit
    recorded human review before proceeding.
12. **Scope discipline** — Phase 4A (deterministic offline baseline comparison)
    is completed and human-approved with limitations (WANG Yiwen 60536848,
    2026-10-23); only in-scope Phase 4A maintenance may proceed without further
    authorization. Phase 4B, production threshold tuning, and unrequested
    features remain prohibited without separate explicit human authorization. Do
    not add unrequested features or duplicate/relocate source trees.