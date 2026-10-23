# Prompt.md — Static Startup Prompt for Coding Agents

This file is the human-readable anchor for the static startup prompt that every
coding agent (OpenCode, Codex, or any equivalent assistant) must be given at the
start of a session. The machine-canonical, versioned form of this prompt lives
in `prompts/prompt_v1.2.yaml`; `prompts/prompt_v1.1.yaml` (prior authoritative)
and `prompts/prompt_v1.0.yaml` (read-only analysis variant) are retained for
traceability. **`prompt_v1.2.yaml` is authoritative for any implementation
work.**

## Prompt preamble (v1.2)

> You are a coding agent operating inside the downstream `TradingAgents` fork
> under the CS5351 course-governance rules. Before you write or change code,
> read, in order: `AGENTS.md`, `architecture-blueprint.md`,
> `docs/architecture/invariants.md`, and `docs/architecture/trace-matrix.md`.
> Then read `pyproject.toml` (Ruff rules, pytest markers) and
> `tests/conftest.py` before touching tests.

## Binding rules (summary — full text in `AGENTS.md`)

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

## Versioning and immutability

- The prompt is intentionally **immutable in intent**: any change to a binding
  rule must be a new versioned file under `prompts/` (e.g. `prompt_v1.3.yaml`)
  and the change from the prior version must be captured in the version
  changelog at the top of the new file.
- The current version marker is `prompt_v1.2.yaml`. The marker is read by any
  agent onboarding to confirm it is using the authoritative prompt.