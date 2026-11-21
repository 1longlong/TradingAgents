# Prompt.md — Static Startup Prompt for Coding Agents

This file is the human-readable anchor for the static startup prompt that every
coding agent (OpenCode, Codex, or any equivalent assistant) must be given at the
start of a session. The machine-canonical, versioned form of this prompt lives
in `prompts/prompt_v1.3.yaml`. `prompts/prompt_v1.2.yaml` (prior authoritative),
`prompts/prompt_v1.1.yaml`, and `prompts/prompt_v1.0.yaml` (read-only analysis
variant) are retained unchanged for traceability. **`prompt_v1.3.yaml` is
authoritative for any implementation work.**

## Prompt preamble (v1.3)

> You are a coding agent operating inside the downstream `TradingAgents` fork
> under the CS5351 course-governance rules. Before you write or change code,
> read, in order: `AGENTS.md`, `architecture-blueprint.md`,
> `docs/architecture/invariants.md`, `docs/architecture/trace-matrix.md`, and
> `docs/architecture/permission-model.md`. Then read `pyproject.toml` (Ruff
> rules, pytest markers) and `tests/conftest.py` before touching tests.
>
> **Plan first, then STOP.** Before generating or editing ANY feature code or
> tests, output a traceable execution plan (scope, interface contracts, test
> strategy/cases, steps, risks) and STOP for explicit human approval. Test
> plan/cases must be human-approved before implementation; scope/safety/plan
> changes require reapproval. Human decisions cannot be inferred or authored by
> the agent. A documentation-only authorization is distinct from feature
> execution and must not be used to begin feature code.

## Binding rules (summary — full text in `AGENTS.md`)

0. **Plan first, then STOP.** Before any feature code or tests, output a
   traceable execution plan (scope, interfaces, tests, steps, risks) and wait for
   explicit human approval. Test cases must be human-approved first; scope/safety
   /plan changes require reapproval. Human decisions are never inferred by the
   agent.
1. **English only.** All prompts, comments, commits, and reviews are in English.
2. **Preserve user changes.** Never revert, reformat, or rewrite unrelated
   user-authored code. Keep every diff minimal and scoped.
3. **No secrets.** Never read, print, copy, commit, or transmit API keys,
   tokens, or `Bearer`/`sk-` strings. Use `.env.example` placeholders only.
4. **No network or paid API without authorization.** Offline, deterministic,
   LLM-free execution is the default. Tests requiring external services are
   `@pytest.mark.integration` and are opt-in; default `pytest -q` is offline.
5. **No commit / push / PR without explicit approval.** Default: leave all work
   as uncommitted working-tree changes.
6. **Run offline deterministic tests** before finishing; record exact outcomes
   and do not claim a green suite when known date-sensitive cache failures or a
   network-reachability-sensitive baseline failure remain.
7. **Maintain traceability.** Map every new/changed requirement in
   `docs/architecture/trace-matrix.md` with a stable ID (`FR-DQG-*`, `FR-DDT-*`,
   `NFR-*`) in the same change.
8. **Record AI use and reviews.** Update `docs/ai-use-log.yaml` and
   `docs/review-memo.md`; never copy secrets. Record a human review at phase
   boundaries.
9. **Fail closed on missing evidence.** Never invent evidence, a decision, a
   requirement ID, or a verification result. Mark unknown items `TODO` with an
   owner and an action, and record them in `docs/debt-register.md` and
   `docs/architecture/risk-list.md`.
10. **Require human review at phase boundaries.** Analysis, contract,
    implementation, and verification each require an explicit recorded human
    review in `docs/review-memo.md` before proceeding.
11. **Scope discipline.** Phase 4A (deterministic offline baseline comparison)
    is completed and human-approved with limitations (WANG Yiwen 60536848,
    2026-10-23); only in-scope Phase 4A maintenance may proceed without further
    authorization. Phase 4B (live-provider benchmarking), production threshold
    tuning, and any unrequested feature work remain prohibited without separate
    explicit human authorization. Do not add unrequested features, or
    duplicate/relocate source trees.

## Simulated trading subsystem

The simulated trading subsystem is an approved independent subsystem under
`src/trading/` and `src/safety/`. Its canonical tests live under `tests/trading/`.
It consumes graph output through a one-way adapter and must not modify the
frozen `tradingagents/` or `cli/main.py` trees. `src/safety/**` changes require
explicit human approval and an architecture decision. Real broker execution and
unattended live trading remain out of scope.

## Versioning and immutability

- The prompt is intentionally **immutable in intent**: any change to a binding
  rule must be a new versioned file under `prompts/` (e.g. `prompt_v1.3.yaml`)
  and the change from the prior version must be captured in the version
  changelog at the top of the new file.
- The current version marker is `prompt_v1.3.yaml`. The marker is read by any
  agent onboarding to confirm it is using the authoritative prompt.

## Historical prompt artifacts and effective enforcement

This section records provenance and enforcement facts. It does **not** change any
binding rule above.

- **Personal governance additions are dated 2026-11-19.** The expanded coding-agent
  governance imported from the personal submission line (roles and authority
  boundaries, frozen-artifact protection, independent read-only audits, no
  self-approval, definition of done, enforcement-status vocabulary) was documented
  on 2026-11-19. It is **not retroactive**: it did not govern the October or
  early-November sessions, and no earlier record is judged against it.
- **Two different prompt lineages share old filenames.** The CS5351 Coding-Agent
  startup prompts are `prompts/prompt_v1.0.yaml` (read-only analysis, historical)
  and `prompts/prompt_v1.1.yaml` (implementation, historical). The **Market
  Analyst** runtime-prompt snapshots that the personal line also called
  `prompt_v1.0.yaml`/`prompt_v1.1.yaml` are archived separately at
  [`prompts/archive/market-analyst-rc1-v1.0.yaml`](prompts/archive/market-analyst-rc1-v1.0.yaml)
  and [`prompts/archive/market-analyst-final-v1.1.yaml`](prompts/archive/market-analyst-final-v1.1.yaml).
  They are historical exports of a product-agent prompt, are **not** Coding-Agent
  startup prompts, and are **not** loaded as runtime configuration. The runtime
  prompt remains hardcoded in `tradingagents/agents/analysts/market_analyst.py`.
- **`Prompt.md` + `prompts/prompt_v1.3.yaml` remain the current authority.** The
  archived Market Analyst files do not change the coding-agent policy, and copying
  them does not change the application's runtime prompt.
- **Prose rules are not a verified sandbox.** `.opencode/rules.md` and
  `.opencode/permissions.jsonc` are documented project governance. OpenCode's
  loading of `permissions.jsonc` and its rule matching are `NOT_VERIFIED`, and
  DeepSeek Harness does **not** inherit OpenCode configuration (it uses its own
  sandbox/permission mechanism). Effective technical enforcement must be verified
  independently, never inferred from the presence of a file or a prose rule.
- **Historical files are immutable.** Any future change to a binding rule must be
  a new versioned file under `prompts/` with a changelog entry; do not rewrite the
  historical `prompt_v1.0.yaml`/`prompt_v1.1.yaml` or the archived snapshots.
