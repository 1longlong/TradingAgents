# TradingAgents Project Covenant

Scope: incremental development of the existing TradingAgents system. Current direct human instructions determine iteration scope; development rules do not expand authorization. Creating governance files does not approve a WebUI design, tests, or safety changes.

## 1. Abstractions and dependencies

1. **Read repository instructions first** — `AGENTS.md`,
   `architecture-blueprint.md`, the files under `docs/architecture/`, the files
   under `docs/code-governance/`, `pyproject.toml`, and `test/conftest.py`.
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
    ADR-013–ADR-018; the simulated-trading subsystem is ADR-019 and PR #5 is
    ADR-012. Phase 4B, production threshold tuning, and unrequested
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
    `.opencode/permissions.jsonc` is defense in depth, not an OS security
    boundary. ADR-031 records verified native V1 loading and bounded file-operation
    probes; untested tools/hosts remain `NOT_VERIFIED`. `.env` reads via arbitrary shell commands cannot be
    blocked reliably by that file.
21. **No MCP or new dependencies without approval** — no MCP server is configured;
    do not add one or add a runtime dependency without explicit human approval.

1. Extend the baseline. Do not replace existing packages, duplicate business logic, or introduce abstractions unrelated to requirements.
2. Assign each architecture element a primary owning module. New layers, frameworks, storage, and dependencies need requirements and architecture rationale. Do not install or upgrade dependencies without approval.
3. Preserve `src/`, `test/offline/`, and `test/live/`, together with existing import and CLI contracts. Do not add governance directories beyond the agreed structure.
4. The existing WebUI belongs to the merged release baseline; new changes still require scoped approval. Do not infer requirements from the deleted demonstration or guesses.

## 2. Test independence

1. Each feature needs at least one negative test, each acceptance criterion a machine check, and each invariant an effective violation test.
2. Derive tests from requirements and observable behavior. Implementation and tests must not share the same faulty calculation as their proof of correctness.
3. Verify must not alter implementation or weaken standards. Return findings to Build. Do not remove assertions, relax thresholds, or report false passes.
4. Run all previous suites each iteration. Record historical failures honestly; they remain blockers and do not excuse new regressions.

## 3. Safety changes and human oversight

1. Obtain human approval of plans and tests before product implementation. Safety-critical changes also need an ADR and human approval.
2. Model outputs are recommendations, not execution authority. UI or LLM behavior must not bypass deterministic rating, time, portfolio, path, credential, memory, or recovery boundaries.
3. Without explicit authorization, do not access real credentials/user data, call paid services, publish, push, merge, or send external messages.
4. Humans maintain `.opencode/rules.md`. Agents cannot modify permissions or rules to authorize themselves. When humans request governance changes, prepare concrete changes and act within that request.
5. Existing approval remains valid for the same explicit scope. Resubmit only changed scope or risk.

## 4. Context freshness and co-evolution

1. Update affected governance rules within one sprint of a requirements change. If old rules affect current safety or correctness, update before dependent coding.
2. Keep requirements, architecture decisions, invariants, traceability, tests, and runtime policies aligned. Empty files do not satisfy documentation requirements.
3. After context compaction or recovery, re-read `AGENTS.md`, this covenant, human-owned rules, relevant invariants, and valid approvals. A compacted summary cannot restore authorization that never existed.
4. Record actual AI use, interventions, reviews, defects, and debt. Do not backdate approvals or invent sessions or contributions.
5. Discovery may start before design artifacts are populated. Use Plan for discussion and Docs for agreed drafts and data validation; product implementation remains gated on the relevant completed artifacts and approvals.

See `docs/code-governance/structural-constraints.md` and `verification-constraints.md` for detailed structure and verification rules.


## Imported core constraints

Release core protections (deterministic evidence, fail-closed gate, output guards,
budget reservations, durable usage, point-in-time checks) remain binding. Core
IDs are `FR-DQG-*`, `FR-DDT-*`, `NFR-*` and `INV-*`; WebUI IDs remain
`REQ-WEB-*` and `INV-WEB-*`. Preserve both sets. The current canonical layout is
`src/` and `test/`; prior root-layout exceptions are historical. No live benchmark,
production threshold tuning, paid service, or additional feature is authorized
by this merge. Release agent-permission proposals remain inactive; the existing
V1 permission configuration is retained without widening it. Human approvals
retain their actual scope, and this merge does not manufacture new approval.
