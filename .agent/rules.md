# Coding-Agent Rules (shared, applied by any agent incl. OpenCode and Codex)

These rules apply to any coding agent working in this repository. They are the
operational form of `AGENTS.md`. Read `AGENTS.md` for the full authoritative
text before editing source or tests.

## Binding rules

1. **Read repository instructions first** — `AGENTS.md`,
   `architecture-blueprint.md`, the files under `docs/architecture/`, the files
   under `docs/code-governance/`, `pyproject.toml`, and `tests/conftest.py`.
2. **English only** for prompts, commits, review comments, and code comments.
3. **Preserve user changes** — do not revert, reformat, or rewrite unrelated
   user-authored code; keep diffs minimal and scoped.
4. **No secrets** — never read, print, copy, commit, or transmit API keys,
   tokens, or `Bearer`/`sk-` strings. Use `.env.example` placeholders only; scan
   the final diff before finishing.
5. **No network or paid API without authorization** — offline, deterministic,
   LLM-free execution is the default; external-service tests are
   `@pytest.mark.integration` and opt-in. An explicit authorization must name the
   run, provider, budget and date; a present key is not authorization.
6. **No commit / push / PR without explicit approval** — default is uncommitted
   working-tree changes. Staging is a write and needs the approved path list.
7. **Use offline deterministic tests** — run them before finishing; report the
   exact command, exit code and output tail; record known failures and never
   claim a green suite when they remain.
8. **Maintain traceability** — map every new/changed requirement in
   `docs/architecture/trace-matrix.md` with a stable ID in the same change. ADR
   and invariant numbers are unique and must match their filenames/headings.
9. **Record AI use and reviews** — update `docs/ai-use-log.yaml` and
   `docs/review-memo.md`; never copy secrets; record the coding application, not
   a model alias, and leave uncertain authorship unresolved.
10. **Fail closed on missing evidence** — mark unknown items `TODO` with an
    owner/action; record in `docs/debt-register.md` and
    `docs/architecture/risk-list.md`. Never invent evidence or a result.
11. **Human review at phase boundaries** — each phase requires an explicit
    recorded human review before proceeding.
12. **Scope discipline** — the delivered tree contains Phase 1–3B, the approved
    Phase 4A comparison, and the token-observability delivery documented as
    ADR-012–ADR-018. Phase 4B, production threshold tuning, and unrequested
    features remain prohibited by default; the token-observability paid campaigns
    ran under dated, run-specific authorizations that do not authorize further
    spend. Do not add unrequested features or duplicate/relocate source trees.
13. **Plan first, then STOP for approval** — before generating or editing any
    feature code, tests or governance, output a traceable execution plan (scope,
    files, interfaces, tests, risks, rollback, verification commands) and
    **STOP** for explicit human approval. Test cases must be human-approved
    before implementation. Scope/safety/frozen-artifact/plan changes require
    reapproval. Human decisions are never inferred or authored by the agent.
14. **Role scope and frozen areas** — operate only within the granted role
    (Planner/Builder/Verifier) and path scope, deny by default. Never edit
    human-only/frozen areas (`.opencode/rules.md`,
    `.opencode/permissions.jsonc`, `.github/**`, dependency files, secrets,
    outside-repo paths); propose instead. Safety-critical changes
    (gate/evaluator/output-guard/fail-closed/budget/permission/prompt) require an
    **ADR + explicit human approval**.
15. **Negative tests and freshness** — every feature/requirement change must add
    at least one **negative** test that pins the fail-closed/invariant-violating
    behavior, and requirement/invariant IDs must appear in the tests. Re-check
    context and rules freshness each sprint or whenever the governing prompt
    version or `AGENTS.md` changes; a stale context must be re-read before any
    edit.
16. **No destructive Git operations** — no force-push, history rewrite, rebase of
    a shared branch, amend of an already-pushed commit, tag move/delete, or
    `git reset --hard` on published work. Do not change branch protection, CI
    triggers, or release tags as part of a code change.
17. **Frozen artifacts stay frozen** — do not edit the registered
    `token_benchmarks/**/specs/**` trees, `MANIFEST.sha256` files, V3 protocol
    documents, `CONFIG_HASH_MANIFEST.csv`, memory baselines, freeze/attestation
    records, or the tags `rc1`, `c3-final-freeze`, `c3-v3-final-freeze`,
    `cand01-v3-final-remediation`. Verify with the freeze scripts; never by hand.
18. **Independent audit discipline** — an audit agent may run tests, read files
    and run read-only git commands, but may not edit the tree, commit, push, or
    change tags. No agent may certify its own work as an independent audit or
    authorize its own paid run, git write, or scope change.
19. **Evidence, not claims** — report what you observed; mark an unrun check
    `NOT_RUN` and an unverified mechanism `NOT_VERIFIED`. Missing usage is
    `null`, never `0`. Never delete, skip, or weaken a test to obtain green.
20. **Permissions are documented-only unless verified** —
    `.opencode/permissions.jsonc` is a project governance artifact whose OpenCode
    loading and rule matching are `NOT_VERIFIED`; it is defense in depth, not a
    security boundary. `.env` reads via arbitrary shell commands cannot be
    blocked reliably by that file. DeepSeek Harness uses its own sandbox and does
    not inherit OpenCode configuration.
21. **No MCP or new dependencies without approval** — no MCP server is configured;
    do not add one or add a runtime dependency without explicit human approval.
