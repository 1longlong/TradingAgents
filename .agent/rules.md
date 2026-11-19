# Coding-Agent Rules (always on)

These rules apply to every coding agent in this repository, including OpenCode,
Codex, and any other AI assistant. They restate `AGENTS.md`; if they conflict,
`AGENTS.md` wins. The static startup prompt is `Prompt.md`;
`prompts/prompt_v1.0.yaml` and `prompts/prompt_v1.1.yaml` are archival exports of
hardcoded runtime prompts, not loaded configuration.

1. **Read before editing.** Read `AGENTS.md`, `architecture-blueprint.md`, the
   files under `docs/architecture/`, and the files in `docs/code-governance/`.
2. **Plan first.** State scope, files, interfaces, tests, risks, and verification
   commands; do not implement until a human approves. Re-approval is required for
   scope, safety, frozen-artifact, or test-plan changes.
3. **Offline default.** Do not call LLM providers, vendors, or paid APIs, and do
   not run the benchmark `run` command, without explicit written authorization
   for that run.
4. **Protect credentials.** Never read, print, copy, commit, or transmit `.env`,
   `.env.enterprise`, keys, tokens, or `Bearer`/`sk-` strings.
5. **Do not rewrite history.** No force push, rebase, amend of pushed commits,
   tag moves/deletes, or `git reset --hard`; no commit/push/PR without approval.
6. **Stay in scope.** Edit only approved files; no mass formatting or unrelated
   fixes; preserve user changes.
7. **Verify and report honestly.** Run the offline tests after changes, report
   the exact command and result, and list known failures. Never fabricate,
   delete, or skip tests; missing usage is `null`, never `0`.
8. **Frozen artifacts stay frozen.** Do not edit registered specs, manifests,
   protocols, memory baselines, or release tags.
9. **No MCP or new dependencies** without approval; this project uses none.
10. **No self-approval.** A coding agent may not authorize its own paid run, git
    write, or scope change, and may not certify its own work as an independent
    audit.
