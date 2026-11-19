# OpenCode Project Rules (always on)

These rules apply to every OpenCode session in this repository. They restate
`AGENTS.md`; if they ever conflict, `AGENTS.md` wins. The static startup prompt is
`Prompt.md`; `prompts/prompt_v1.0.yaml` and `prompts/prompt_v1.1.yaml` are
archival exports of hardcoded runtime prompts, not configuration this repository
loads.

1. **Read first.** Read `AGENTS.md`, `architecture-blueprint.md`, the files under
   `docs/architecture/`, and the files in `docs/code-governance/` before
   editing.
2. **Plan, then wait.** Post scope, files, tests, risks, and verification
   commands; implement only after explicit human approval. Re-ask if scope
   changes.
3. **No spend, no network.** Do not run paid LLM/vendor pipelines, benchmarks, or
   `curl`/`wget` without explicit written authorization for that run. The default
   is offline and deterministic.
4. **No secrets.** Never read, print, copy, commit, or transmit `.env`,
   `.env.enterprise`, API keys, tokens, or `Bearer`/`sk-` strings. Use
   `.env.example` placeholders.
5. **No git writes.** No commit, push, PR, merge, tag, force-push, rebase, or
   history rewrite without explicit approval. Read-only git is fine.
6. **Keep scope.** Edit only approved files; no drive-by refactors, mass
   formatting, or unrelated changes. Preserve user-authored work.
7. **Test after changes.** Run
   `TZ=UTC PYTHONPATH=. .venv/bin/python -m pytest tests -q` and report the exact
   command, exit code, and any known failures. Never delete/skip tests to get
   green.
8. **Evidence, not claims.** Report what you observed; mark unrun checks
   `NOT_RUN` and unverified mechanisms `NOT_VERIFIED`. Missing usage is `null`,
   never `0`.
9. **Frozen artifacts are read-only.** Do not edit `specs/`, `MANIFEST.sha256`,
   protocol/freeze records, memory baselines, or release tags.
10. **No MCP, no new dependencies.** No MCP server is used in this project. Do not
    add one or add a runtime dependency without approval.
11. **Permissions file is documented-only.** `.opencode/permissions.jsonc` is a
    project artifact whose OpenCode loading and rule matching are `NOT_VERIFIED`;
    it is defense in depth, not a security boundary. `.env` reads via arbitrary
    shell commands cannot be blocked reliably by that file.
